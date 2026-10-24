"""Strict CCSDS CDM ingestion for event-bound and standalone Foster inputs.

Imported source identity is user-declared and is not independently authenticated.
Only complete Cartesian 6x6 covariance matrices are accepted. NASA CARA KVN
components use each object's documented RTN basis. TraCSS JSON-TraCSS v2.0 is
accepted only with EME2000 states; its documented Object 1 RTN basis is used for
both covariance rotations. ITRF states fail closed because no validated
Earth-orientation state transform or covariance propagation is implemented.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET

import numpy as np

from app.services.collision_probability import CovarianceInput, HardBodyRadiusInput, _validate_covariance


MAX_CDM_XML_BYTES = 1_000_000
COORDINATES = ("R", "T", "N", "RDOT", "TDOT", "NDOT")
# The supported state frames are either used in local reference fixtures or in
# a format with validated frame semantics. TraCSS JSON-ST's ITRF is rejected.
SUPPORTED_CDM_REFERENCE_FRAMES = frozenset({"TEME", "EME2000", "GCRF"})


@dataclass(frozen=True)
class CdmObjectInput:
    object_designator: str
    object_id: str | None
    object_name: str | None
    covariance: CovarianceInput
    position_km: list[float]
    velocity_km_s: list[float]
    object_hbr_km: float | None = None


@dataclass(frozen=True)
class CdmInputs:
    tca_utc: str
    originator: str | None
    created_utc: str | None
    inputs: tuple[CdmObjectInput, CdmObjectInput]
    hbr: HardBodyRadiusInput
    input_sha256: str
    message_id: str | None = None
    source_pc: float | None = None
    source_pc_method: str | None = None
    source_miss_distance_km: float | None = None
    source_format: str = "CCSDS-CDM"
    retrieved_utc: str | None = None


def parse_cdm_xml(xml_text: str, *, source_label: str, retrieved_at_utc: str | None = None) -> CdmInputs:
    if not isinstance(xml_text, str) or not xml_text.strip():
        raise ValueError("CDM_XML_EMPTY")
    raw = xml_text.encode("utf-8")
    if len(raw) > MAX_CDM_XML_BYTES:
        raise ValueError("CDM_XML_TOO_LARGE")
    if re.search(r"<!\s*(DOCTYPE|ENTITY)\b", xml_text, re.IGNORECASE):
        raise ValueError("CDM_XML_DTD_NOT_ALLOWED")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError("CDM_XML_MALFORMED") from exc
    if _local_name(root.tag).lower() != "cdm":
        raise ValueError("CDM_ROOT_REQUIRED")

    segments = [node for node in root.iter() if _local_name(node.tag).lower() == "segment"]
    if len(segments) != 2:
        raise ValueError("CDM_MUST_CONTAIN_TWO_SEGMENTS")
    relative = _find_node(root, "relativeMetadata")
    if relative is None:
        raise ValueError("CDM_RELATIVE_METADATA_REQUIRED")
    tca_raw = _find_text(relative, "TCA")
    tca = _parse_utc(tca_raw, "CDM_TCA_INVALID")
    hbr_node = _find_node(relative, "HARD_BODY_RADIUS")
    if hbr_node is None:
        raise ValueError("CDM_HBR_MISSING")
    hbr_value = _positive_number(hbr_node.text, "CDM_HBR_INVALID")
    hbr_km = _length_to_km(hbr_value, hbr_node.attrib.get("units"), "CDM_HBR_UNITS_UNSUPPORTED")

    originator = _find_text(root, "ORIGINATOR")
    created_raw = _find_text(root, "CREATED")
    created = _parse_utc(created_raw, "CDM_CREATED_INVALID") if created_raw else None
    label = source_label.strip() if isinstance(source_label, str) else ""
    if not label:
        raise ValueError("CDM_SOURCE_LABEL_REQUIRED")
    sha256 = hashlib.sha256(raw).hexdigest()
    recorded_source = f"User-supplied CCSDS CDM XML; label={label}; declared_originator={originator or 'not provided'}"
    imported_at = _parse_utc(retrieved_at_utc, "CDM_RETRIEVED_AT_INVALID") if retrieved_at_utc else created or datetime.now(timezone.utc).isoformat()

    segment_frames: list[str] = []
    for segment in segments:
        metadata = _find_node(segment, "metadata")
        if metadata is None:
            raise ValueError("CDM_OBJECT_METADATA_OR_COVARIANCE_MISSING")
        frame = _find_text(metadata, "REF_FRAME")
        if not frame:
            raise ValueError("CDM_REFERENCE_FRAME_MISSING")
        segment_frames.append(frame)
    if len(set(segment_frames)) != 1:
        raise ValueError("CDM_FRAME_MISMATCH")
    unsupported_frames = sorted(set(segment_frames) - SUPPORTED_CDM_REFERENCE_FRAMES)
    if unsupported_frames:
        raise ValueError("CDM_REFERENCE_FRAME_UNSUPPORTED")

    parsed_inputs: list[CdmObjectInput] = []
    for segment, frame in zip(segments, segment_frames):
        metadata = _find_node(segment, "metadata")
        matrix_node = _find_node(segment, "covarianceMatrix")
        if metadata is None or matrix_node is None:
            raise ValueError("CDM_OBJECT_METADATA_OR_COVARIANCE_MISSING")
        designator = _find_text(metadata, "OBJECT_DESIGNATOR")
        if not designator:
            raise ValueError("CDM_OBJECT_DESIGNATOR_MISSING")
        covariance_type = (_find_text(metadata, "COVARIANCE_TYPE") or "").upper()
        if covariance_type != "CARTESIAN":
            raise ValueError("CDM_COVARIANCE_TYPE_UNSUPPORTED")
        covariance_frame = _find_text(metadata, "COV_REF_FRAME")
        if covariance_frame and covariance_frame.upper() != "RTN":
            raise ValueError("CDM_COVARIANCE_FRAME_UNSUPPORTED")
        matrix = _parse_cartesian_covariance(matrix_node)
        raw_covariance = CovarianceInput(
            object_id=designator,
            frame=frame,
            epoch=tca,
            matrix=matrix,
            units={"position": "km^2", "velocity": "km^2/s^2", "position_velocity_cross": "km^2/s"},
            source=recorded_source,
            source_type="user_supplied",
            source_timestamp=imported_at,
            input_hash=sha256,
            is_synthetic=False,
        )
        validated_raw, raw_reason, _ = _validate_covariance(raw_covariance)
        if raw_reason or validated_raw is None:
            raise ValueError("CDM_COVARIANCE_INVALID")
        state_node = _find_node(segment, "stateVector")
        if state_node is None:
            raise ValueError("CDM_TCA_STATE_MISSING")
        position, velocity = _parse_state_vector(state_node)
        rotation = _rtn_to_reference(position, velocity)
        position_covariance = rotation @ np.asarray(matrix, dtype=float)[:3, :3] @ rotation.T
        covariance = CovarianceInput(
            object_id=designator,
            frame=frame,
            epoch=tca,
            matrix=position_covariance.tolist(),
            units={"position": "km^2"},
            source=recorded_source + "; RTN position covariance rotated into declared CDM reference frame using the CDM TCA state vector",
            source_type="user_supplied",
            source_timestamp=imported_at,
            input_hash=sha256,
            is_synthetic=False,
        )
        validated, reason, _ = _validate_covariance(covariance)
        if reason or validated is None:
            raise ValueError("CDM_COVARIANCE_INVALID")
        parsed_inputs.append(CdmObjectInput(
            object_designator=designator,
            object_id=_find_text(metadata, "OBJECT_ID"),
            object_name=_find_text(metadata, "OBJECT_NAME"),
            covariance=covariance,
            position_km=position,
            velocity_km_s=velocity,
        ))
    if parsed_inputs[0].object_designator == parsed_inputs[1].object_designator:
        raise ValueError("CDM_OBJECT_IDENTIFIERS_NOT_DISTINCT")

    hbr = HardBodyRadiusInput(
        value_km=hbr_km,
        source="supplied",
        source_type="user_supplied",
        description=f"Combined HBR imported from user-supplied CDM ({label}); originator is not authenticated.",
        source_timestamp=imported_at,
        input_hash=sha256,
        is_synthetic=False,
    )
    source_pc = _find_text(relative, "COLLISION_PROBABILITY")
    parsed_source_pc = _finite_number(source_pc, "CDM_SOURCE_PC_INVALID") if source_pc else None
    if parsed_source_pc is not None and not 0.0 <= parsed_source_pc <= 1.0:
        raise ValueError("CDM_SOURCE_PC_INVALID")
    miss_node = _find_node(relative, "MISS_DISTANCE")
    source_miss = None
    if miss_node is not None and miss_node.text:
        source_miss = _length_to_km(
            _positive_number(miss_node.text, "CDM_MISS_DISTANCE_INVALID"),
            miss_node.attrib.get("units"),
            "CDM_MISS_DISTANCE_UNITS_UNSUPPORTED",
        )
    return CdmInputs(
        tca_utc=tca,
        originator=originator,
        created_utc=created,
        inputs=(parsed_inputs[0], parsed_inputs[1]),
        hbr=hbr,
        input_sha256=sha256,
        message_id=_find_text(root, "MESSAGE_ID"),
        source_pc=parsed_source_pc,
        source_pc_method=_find_text(relative, "COLLISION_PROBABILITY_METHOD"),
        source_miss_distance_km=source_miss,
        source_format="CCSDS CDM XML",
        retrieved_utc=imported_at if retrieved_at_utc else None,
    )


def parse_cdm_input(text: str, *, source_label: str, retrieved_at_utc: str | None = None) -> CdmInputs:
    """Parse a CCSDS CDM XML or KVN document without treating it as live data."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("CDM_XML_EMPTY")
    if text.lstrip().startswith("<"):
        return parse_cdm_xml(text, source_label=source_label, retrieved_at_utc=retrieved_at_utc)
    if text.lstrip().startswith("{"):
        return _parse_tracss_json(text, source_label=source_label, retrieved_at_utc=retrieved_at_utc)
    return _parse_cdm_kvn(text, source_label=source_label, retrieved_at_utc=retrieved_at_utc)


def _parse_tracss_json(text: str, *, source_label: str, retrieved_at_utc: str | None = None) -> CdmInputs:
    """Parse TraCSS JSON-TraCSS CDMs, whose specified state frame is EME2000.

    JSON-ST uses ITRF states and is deliberately rejected: this service does not
    perform the Earth-orientation transform needed to interpret ITRF velocity
    vectors as inertial encounter velocities.
    """
    raw = text.encode("utf-8")
    if len(raw) > MAX_CDM_XML_BYTES:
        raise ValueError("CDM_XML_TOO_LARGE")
    label = source_label.strip() if isinstance(source_label, str) else ""
    if not label:
        raise ValueError("CDM_SOURCE_LABEL_REQUIRED")
    try:
        document = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("CDM_JSON_MALFORMED") from exc
    records = document.get("tracssCdms") if isinstance(document, dict) else None
    if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
        raise ValueError("TRACSS_CDM_SINGLE_RECORD_REQUIRED")
    record = records[0]
    if str(record.get("TRACSS_CDM_VERS", "")) != "2.0":
        raise ValueError("TRACSS_CDM_VERSION_UNSUPPORTED")
    tca = _parse_utc(_tracss_utc(record.get("TCA"), "CDM_TCA_INVALID"), "CDM_TCA_INVALID")
    created_raw = record.get("CREATION_DATE")
    created = _parse_utc(_tracss_utc(created_raw, "CDM_CREATED_INVALID"), "CDM_CREATED_INVALID") if created_raw else None
    digest = hashlib.sha256(raw).hexdigest()
    originator = str(record.get("ORIGINATOR") or "") or None
    source = f"User-supplied TraCSS JSON-TraCSS CDM 2.0; label={label}; declared_originator={originator or 'not provided'}"
    frame_values = [str(record.get(f"SAT{i}_REF_FRAME", "")).upper() for i in (1, 2)]
    if any(not frame for frame in frame_values):
        raise ValueError("CDM_REFERENCE_FRAME_MISSING")
    if len(set(frame_values)) != 1:
        raise ValueError("CDM_FRAME_MISMATCH")
    frame = frame_values[0]
    if frame != "EME2000":
        raise ValueError("CDM_REFERENCE_FRAME_UNSUPPORTED")

    raw_objects: list[tuple[str, str | None, list[float], list[float], np.ndarray, float]] = []
    for index in (1, 2):
        prefix = f"SAT{index}_"
        designator = record.get(prefix + "OBJECT_DESIGNATOR")
        if designator is None or not str(designator).strip():
            raise ValueError("CDM_OBJECT_DESIGNATOR_MISSING")
        position: list[float] = []
        velocity: list[float] = []
        for axis in ("X", "Y", "Z"):
            position.append(_tracss_vector_component(record, prefix, axis, "length"))
        for axis in ("X_DOT", "Y_DOT", "Z_DOT"):
            velocity.append(_tracss_vector_component(record, prefix, axis, "velocity"))
        matrix = _parse_tracss_json_rtn_covariance(record, prefix, tca)
        hbr = _tracss_length(record.get(prefix + "HBR"), record.get(prefix + "HBR_UNIT"), "CDM_HBR_UNITS_UNSUPPORTED")
        if hbr <= 0:
            raise ValueError("CDM_HBR_INVALID")
        raw_objects.append((str(designator).strip(), str(record.get(prefix + "OBJECT_NAME") or "") or None, position, velocity, matrix, hbr))
    if raw_objects[0][0] == raw_objects[1][0]:
        raise ValueError("CDM_OBJECT_IDENTIFIERS_NOT_DISTINCT")

    # TraCSS Spec 001 release 2.1 defines the covariance elements in Object 1's
    # RTN basis. Use that single documented basis for both objects.
    rotation = _rtn_to_reference(raw_objects[0][2], raw_objects[0][3])
    parsed: list[CdmObjectInput] = []
    for designator, name, position, velocity, matrix, hbr in raw_objects:
        covariance_matrix = rotation @ matrix[:3, :3] @ rotation.T
        covariance = CovarianceInput(
            object_id=designator,
            frame=frame,
            epoch=tca,
            matrix=covariance_matrix.tolist(),
            units={"position": "km^2"},
            source=source + "; RTN position covariance rotated into EME2000 using Object 1's TCA RTN basis per TraCSS Spec 001 v2.1",
            source_type="user_supplied",
            source_timestamp=created or datetime.now(timezone.utc).isoformat(),
            input_hash=digest,
        )
        validated, reason, _ = _validate_covariance(covariance)
        if reason or validated is None:
            raise ValueError("CDM_COVARIANCE_INVALID")
        parsed.append(CdmObjectInput(
            object_designator=designator,
            object_id=None,
            object_name=name,
            covariance=covariance,
            position_km=position,
            velocity_km_s=velocity,
            object_hbr_km=hbr,
        ))

    source_pc = record.get("COLLISION_PROBABILITY")
    parsed_source_pc = _finite_number(str(source_pc), "CDM_SOURCE_PC_INVALID") if source_pc not in (None, "") else None
    if parsed_source_pc is not None and not 0.0 <= parsed_source_pc <= 1.0:
        raise ValueError("CDM_SOURCE_PC_INVALID")
    miss_raw = record.get("MISS_DISTANCE")
    source_miss = _tracss_length(miss_raw, record.get("MISS_DISTANCE_UNIT"), "CDM_MISS_DISTANCE_UNITS_UNSUPPORTED") if miss_raw not in (None, "") else None
    hbr_km = raw_objects[0][5] + raw_objects[1][5]
    hbr = HardBodyRadiusInput(
        value_km=hbr_km,
        source="supplied",
        source_type="user_supplied",
        description=(
            "Combined HBR is the sum of the two per-object HBR values explicitly supplied by the TraCSS CDM: "
            f"{raw_objects[0][0]}={raw_objects[0][5]:.12g} km; {raw_objects[1][0]}={raw_objects[1][5]:.12g} km. "
            "The declared originator is not authenticated."
        ),
        source_timestamp=_parse_utc(retrieved_at_utc, "CDM_RETRIEVED_AT_INVALID") if retrieved_at_utc else created or datetime.now(timezone.utc).isoformat(),
        input_hash=digest,
    )
    return CdmInputs(
        tca_utc=tca,
        originator=originator,
        created_utc=created,
        inputs=(parsed[0], parsed[1]),
        hbr=hbr,
        input_sha256=digest,
        message_id=str(record.get("MESSAGE_ID") or "") or None,
        source_pc=parsed_source_pc,
        source_pc_method=str(record.get("COLLISION_PROBABILITY_METHOD") or "") or None,
        source_miss_distance_km=source_miss,
        source_format="TraCSS JSON-TraCSS CDM 2.0",
        retrieved_utc=_parse_utc(retrieved_at_utc, "CDM_RETRIEVED_AT_INVALID") if retrieved_at_utc else None,
    )


def _parse_tracss_json_rtn_covariance(record: dict, prefix: str, epoch: str) -> np.ndarray:
    matrix = np.zeros((6, 6), dtype=float)
    for row, axis in enumerate(COORDINATES):
        for col in range(row + 1):
            other = COORDINATES[col]
            key = f"C{axis}_{other}"
            field = prefix + key
            if field not in record or prefix + key + "_UNIT" not in record:
                raise ValueError("CDM_COVARIANCE_MATRIX_INCOMPLETE")
            matrix[row, col] = _unit_convert_covariance(str(record[field]), str(record[prefix + key + "_UNIT"]), key)
            matrix[col, row] = matrix[row, col]
    raw = CovarianceInput(
        object_id=str(record.get(prefix + "OBJECT_DESIGNATOR", "")),
        frame="RTN",
        epoch=epoch,
        matrix=matrix.tolist(),
        units={"position": "km^2", "velocity": "km^2/s^2", "position_velocity_cross": "km^2/s"},
        source="TraCSS JSON-TraCSS covariance fields",
        source_type="user_supplied",
    )
    validated, reason, _ = _validate_covariance(raw)
    if reason or validated is None:
        raise ValueError("CDM_COVARIANCE_INVALID")
    return matrix


def _tracss_vector_component(record: dict, prefix: str, field: str, kind: str) -> float:
    value_key, unit_key = prefix + field, prefix + field + "_UNIT"
    if value_key not in record or unit_key not in record:
        raise ValueError("CDM_TCA_STATE_MISSING" if value_key not in record else "CDM_TCA_STATE_UNITS_UNSUPPORTED")
    unit = str(record[unit_key]).strip().lower()
    factors = {"length": {"km": 1.0, "m": 0.001}, "velocity": {"km/s": 1.0, "m/s": 0.001}}
    if unit not in factors[kind]:
        raise ValueError("CDM_TCA_STATE_UNITS_UNSUPPORTED")
    return _finite_number(str(record[value_key]), "CDM_TCA_STATE_INVALID") * factors[kind][unit]


def _tracss_length(value: str | None, units: str | None, reason: str) -> float:
    number = _finite_number(value, "CDM_HBR_INVALID" if "HBR" in reason else "CDM_MISS_DISTANCE_INVALID")
    return _length_to_km(number, units, reason)


def _tracss_utc(value: object, reason: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(reason)
    cleaned = value.strip()
    if not re.search(r"(?:Z|[+-]\d\d:\d\d)$", cleaned):
        cleaned += "Z"  # TraCSS CDM specification declares these timestamps UTC.
    return cleaned


def _parse_cdm_kvn(text: str, *, source_label: str, retrieved_at_utc: str | None = None) -> CdmInputs:
    """Parse the CCSDS key-value CDM subset used by NASA CARA reference files."""
    raw = text.encode("utf-8")
    if len(raw) > MAX_CDM_XML_BYTES:
        raise ValueError("CDM_XML_TOO_LARGE")
    label = source_label.strip() if isinstance(source_label, str) else ""
    if not label:
        raise ValueError("CDM_SOURCE_LABEL_REQUIRED")
    globals_: dict[str, str] = {}
    objects: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    comments: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.upper().startswith("COMMENT "):
            comments.append(stripped[8:].strip())
            continue
        match = re.match(r"^([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$", stripped, re.IGNORECASE)
        if not match:
            continue
        key, value = match.group(1).upper(), match.group(2)
        if key == "OBJECT" and value.upper() in {"OBJECT1", "OBJECT2"}:
            current = {}
            objects.append(current)
        elif current is None:
            globals_[key] = value
        else:
            current[key] = value
    if len(objects) != 2:
        raise ValueError("CDM_MUST_CONTAIN_TWO_SEGMENTS")
    tca = _parse_cdm_kvn_utc(globals_.get("TCA"), "CDM_TCA_INVALID")
    hbr_match = next((re.search(r"^HBR\s*=\s*([^\[]+)\s*\[([^\]]+)\]", value, re.IGNORECASE) for value in comments if re.match(r"^HBR\s*=", value, re.IGNORECASE)), None)
    if not hbr_match:
        raise ValueError("CDM_HBR_MISSING")
    hbr_km = _length_to_km(_positive_number(hbr_match.group(1), "CDM_HBR_INVALID"), hbr_match.group(2), "CDM_HBR_UNITS_UNSUPPORTED")
    frames = {item.get("REF_FRAME") for item in objects}
    if None in frames:
        raise ValueError("CDM_REFERENCE_FRAME_MISSING")
    if len(frames) != 1:
        raise ValueError("CDM_FRAME_MISMATCH")
    frame = next(iter(frames))
    if frame not in {"TEME", "EME2000", "GCRF"}:
        raise ValueError("CDM_REFERENCE_FRAME_UNSUPPORTED")
    digest = hashlib.sha256(raw).hexdigest()
    created_at = _parse_cdm_kvn_utc(globals_.get("CREATION_DATE"), "CDM_CREATED_INVALID") if globals_.get("CREATION_DATE") else None
    imported_at = _parse_utc(retrieved_at_utc, "CDM_RETRIEVED_AT_INVALID") if retrieved_at_utc else created_at or datetime.now(timezone.utc).isoformat()
    source = f"User-supplied CCSDS CDM KVN; label={label}; declared_originator={globals_.get('ORIGINATOR', 'not provided')}"
    parsed: list[CdmObjectInput] = []
    for item in objects:
        designator = item.get("OBJECT_DESIGNATOR")
        if not designator:
            raise ValueError("CDM_OBJECT_DESIGNATOR_MISSING")
        covariance_frame = item.get("COV_REF_FRAME")
        if covariance_frame and covariance_frame.upper() != "RTN":
            raise ValueError("CDM_COVARIANCE_FRAME_UNSUPPORTED")
        # CARA KVN uses R/T/N covariance element names and documents these as
        # RTN covariance; each object's own state defines the RTN basis.
        matrix = _parse_kvn_rtn_covariance(item)
        position, velocity = _parse_kvn_state(item)
        rotation = _rtn_to_reference(position, velocity)
        raw_cov = CovarianceInput(
            object_id=designator, frame="RTN", epoch=tca, matrix=matrix,
            units={"position": "km^2", "velocity": "km^2/s^2", "position_velocity_cross": "km^2/s"},
            source=source + "; documented RTN covariance", source_type="user_supplied",
            source_timestamp=imported_at, input_hash=digest,
        )
        validated_raw, reason, _ = _validate_covariance(raw_cov)
        if reason or validated_raw is None:
            raise ValueError("CDM_COVARIANCE_INVALID")
        position_covariance = rotation @ np.asarray(matrix, dtype=float)[:3, :3] @ rotation.T
        covariance = CovarianceInput(
            object_id=designator, frame=frame, epoch=tca, matrix=position_covariance.tolist(),
            units={"position": "km^2"},
            source=source + "; RTN position covariance rotated to the declared CDM state frame using that object's CDM state vector",
            source_type="user_supplied", source_timestamp=imported_at, input_hash=digest,
        )
        validated, reason, _ = _validate_covariance(covariance)
        if reason or validated is None:
            raise ValueError("CDM_COVARIANCE_INVALID")
        parsed.append(CdmObjectInput(
            object_designator=designator, object_id=item.get("OBJECT_ID"),
            object_name=item.get("OBJECT_NAME"), covariance=covariance,
            position_km=position, velocity_km_s=velocity,
        ))
    if parsed[0].object_designator == parsed[1].object_designator:
        raise ValueError("CDM_OBJECT_IDENTIFIERS_NOT_DISTINCT")
    hbr = HardBodyRadiusInput(
        value_km=hbr_km, source="supplied", source_type="user_supplied",
        description=f"Combined HBR imported from user-supplied CDM KVN ({label}); originator is not authenticated.",
        source_timestamp=imported_at, input_hash=digest,
    )
    source_pc = _finite_number(globals_.get("COLLISION_PROBABILITY"), "CDM_SOURCE_PC_INVALID") if globals_.get("COLLISION_PROBABILITY") else None
    if source_pc is not None and not 0.0 <= source_pc <= 1.0:
        raise ValueError("CDM_SOURCE_PC_INVALID")
    miss_raw = globals_.get("MISS_DISTANCE")
    source_miss = None
    if miss_raw:
        parsed_miss = re.fullmatch(r"\s*([^\s\[]+)\s*\[([^\]]+)\]\s*", miss_raw)
        if not parsed_miss:
            raise ValueError("CDM_MISS_DISTANCE_INVALID")
        source_miss = _length_to_km(_positive_number(parsed_miss.group(1), "CDM_MISS_DISTANCE_INVALID"), parsed_miss.group(2), "CDM_MISS_DISTANCE_UNITS_UNSUPPORTED")
    return CdmInputs(
        tca_utc=tca, originator=globals_.get("ORIGINATOR"), created_utc=created_at or imported_at,
        inputs=(parsed[0], parsed[1]), hbr=hbr, input_sha256=digest,
        message_id=globals_.get("MESSAGE_ID"), source_pc=source_pc,
        source_pc_method=globals_.get("COLLISION_PROBABILITY_METHOD"),
        source_miss_distance_km=source_miss,
        source_format="CCSDS CDM KVN",
        retrieved_utc=imported_at if retrieved_at_utc else None,
    )


def _parse_kvn_rtn_covariance(item: dict[str, str]) -> list[list[float]]:
    matrix = np.zeros((6, 6), dtype=float)
    for row, axis in enumerate(COORDINATES):
        for col in range(row + 1):
            other = COORDINATES[col]
            key = f"C{axis}_{other}"
            if key not in item:
                raise ValueError("CDM_COVARIANCE_MATRIX_INCOMPLETE")
            raw = item[key]
            match = re.fullmatch(r"\s*([^\s\[]+)\s*\[([^\]]+)\]\s*", raw)
            if not match:
                raise ValueError("CDM_COVARIANCE_UNITS_UNSUPPORTED")
            matrix[row, col] = _unit_convert_covariance(match.group(1), match.group(2), key)
            matrix[col, row] = matrix[row, col]
    return matrix.tolist()


def _parse_kvn_state(item: dict[str, str]) -> tuple[list[float], list[float]]:
    position: list[float] = []
    velocity: list[float] = []
    for axis in ("X", "Y", "Z"):
        for suffix, kind, target in (("", "length", position), ("_DOT", "velocity", velocity)):
            value = item.get(axis + suffix)
            match = re.fullmatch(r"\s*([^\s\[]+)\s*\[([^\]]+)\]\s*", value or "")
            if not match:
                raise ValueError("CDM_TCA_STATE_MISSING" if value is None else "CDM_TCA_STATE_UNITS_UNSUPPORTED")
            number = _finite_number(match.group(1), "CDM_TCA_STATE_INVALID")
            unit = match.group(2).lower()
            factors = {"length": {"km": 1.0, "m": 0.001}, "velocity": {"km/s": 1.0, "m/s": 0.001}}
            if unit not in factors[kind]:
                raise ValueError("CDM_TCA_STATE_UNITS_UNSUPPORTED")
            target.append(number * factors[kind][unit])
    return position, velocity


def _parse_cdm_kvn_utc(value: str | None, reason: str) -> str:
    # CCSDS CDM KVN time tags are UTC; unlike XML, the KVN form commonly omits Z.
    if value and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?", value.strip()):
        value = value.strip() + "Z"
    return _parse_utc(value, reason)


def _parse_cartesian_covariance(node: ET.Element) -> list[list[float]]:
    entries: dict[str, float] = {}
    for child in node.iter():
        name = _local_name(child.tag).upper()
        if name.startswith("C") and "_" in name:
            entries[name] = _unit_convert_covariance(child.text, child.attrib.get("units"), name)
    matrix = np.zeros((6, 6), dtype=float)
    for row, row_axis in enumerate(COORDINATES):
        for col in range(row + 1):
            col_axis = COORDINATES[col]
            name = f"C{row_axis}_{col_axis}"
            if name not in entries:
                raise ValueError("CDM_COVARIANCE_MATRIX_INCOMPLETE")
            matrix[row, col] = entries[name]
            matrix[col, row] = entries[name]
    if len(entries) != 21:
        raise ValueError("CDM_COVARIANCE_MATRIX_UNEXPECTED_FIELDS")
    if not np.isfinite(matrix).all():
        raise ValueError("CDM_COVARIANCE_INVALID")
    return matrix.tolist()


def _unit_convert_covariance(value: str | None, units: str | None, name: str) -> float:
    numeric = _finite_number(value, "CDM_COVARIANCE_VALUE_INVALID")
    normalized = (units or "").replace(" ", "").replace("**", "^").replace("²", "^2").lower()
    row_axis, col_axis = name[1:].split("_", 1)
    position_count = sum(axis in {"R", "T", "N"} for axis in (row_axis, col_axis))
    if position_count == 2:
        allowed = {"km^2": 1.0, "km2": 1.0, "m^2": 1e-6, "m2": 1e-6}
    elif position_count == 1:
        allowed = {"km^2/s": 1.0, "km2/s": 1.0, "m^2/s": 1e-6, "m2/s": 1e-6}
    else:
        allowed = {"km^2/s^2": 1.0, "km2/s2": 1.0, "m^2/s^2": 1e-6, "m2/s2": 1e-6}
    if normalized not in allowed:
        raise ValueError("CDM_COVARIANCE_UNITS_UNSUPPORTED")
    converted = numeric * allowed[normalized]
    if not math.isfinite(converted):
        raise ValueError("CDM_COVARIANCE_VALUE_INVALID")
    return converted


def _length_to_km(value: float, units: str | None, reason: str) -> float:
    normalized = (units or "").strip().lower()
    if normalized == "m":
        return value / 1000.0
    if normalized == "km":
        return value
    raise ValueError(reason)


def _parse_state_vector(node: ET.Element) -> tuple[list[float], list[float]]:
    position = [_state_value(node, axis, "length") for axis in ("X", "Y", "Z")]
    velocity = [_state_value(node, f"{axis}_DOT", "velocity") for axis in ("X", "Y", "Z")]
    return position, velocity


def _state_value(node: ET.Element, name: str, kind: str) -> float:
    field = _find_node(node, name)
    if field is None:
        raise ValueError("CDM_TCA_STATE_MISSING")
    value = _finite_number(field.text, "CDM_TCA_STATE_INVALID")
    units = (field.attrib.get("units") or "").strip().lower()
    factors = {"length": {"km": 1.0, "m": 0.001}, "velocity": {"km/s": 1.0, "m/s": 0.001}}
    if units not in factors[kind]:
        raise ValueError("CDM_TCA_STATE_UNITS_UNSUPPORTED")
    converted = value * factors[kind][units]
    if not math.isfinite(converted):
        raise ValueError("CDM_TCA_STATE_INVALID")
    return converted


def _rtn_to_reference(position_km: list[float], velocity_km_s: list[float]) -> np.ndarray:
    position = np.asarray(position_km, dtype=float)
    velocity = np.asarray(velocity_km_s, dtype=float)
    radius = float(np.linalg.norm(position))
    angular_momentum = np.cross(position, velocity)
    angular_momentum_norm = float(np.linalg.norm(angular_momentum))
    if radius <= 0 or angular_momentum_norm <= 0 or not np.isfinite(position).all() or not np.isfinite(velocity).all():
        raise ValueError("CDM_TCA_STATE_INVALID")
    radial = position / radius
    normal = angular_momentum / angular_momentum_norm
    transverse = np.cross(normal, radial)
    return np.column_stack((radial, transverse, normal))


def _positive_number(value: str | None, reason: str) -> float:
    number = _finite_number(value, reason)
    if number <= 0:
        raise ValueError(reason)
    return number


def _finite_number(value: str | None, reason: str) -> float:
    try:
        number = float(value) if value is not None else math.nan
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(reason) from exc
    if not math.isfinite(number):
        raise ValueError(reason)
    return number


def _parse_utc(value: str | None, reason: str) -> str:
    if not value:
        raise ValueError(reason)
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(reason) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(reason)
    return parsed.astimezone(timezone.utc).isoformat()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_node(parent: ET.Element, name: str) -> ET.Element | None:
    expected = name.lower()
    return next((node for node in parent.iter() if _local_name(node.tag).lower() == expected), None)


def _find_text(parent: ET.Element, name: str) -> str | None:
    node = _find_node(parent, name)
    value = node.text.strip() if node is not None and node.text else ""
    return value or None
