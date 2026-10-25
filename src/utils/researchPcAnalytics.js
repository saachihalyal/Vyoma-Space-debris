const finite = (value) => typeof value === "number" && Number.isFinite(value);

function geometryKey(event) {
  const physics = event?.physics_result || {};
  const tca = physics.tca?.value;
  const miss = Number(physics.miss_distance?.value);
  const speed = Number(physics.relative_speed_at_tca?.value);
  if (typeof tca !== "string" || !Number.isFinite(Date.parse(tca)) || !Number.isFinite(miss) || !Number.isFinite(speed)) return null;
  return `${Math.round(Date.parse(tca))}|${miss.toPrecision(4)}|${speed.toPrecision(4)}`;
}

export function groupCoLocatedEvents(events = []) {
  const buckets = new Map();
  for (const event of events) {
    const key = geometryKey(event);
    if (!key) continue;
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(event);
  }
  const groups = [];
  for (const candidates of buckets.values()) {
    if (candidates.length < 2) continue;
    const remaining = new Set(candidates);
    while (remaining.size) {
      const members = [remaining.values().next().value];
      remaining.delete(members[0]);
      for (let i = 0; i < members.length; i += 1) {
        const ids = new Set([members[i]?.primary?.id, members[i]?.secondary?.id].filter(Boolean));
        for (const candidate of [...remaining]) {
          if ([candidate?.primary?.id, candidate?.secondary?.id].some((id) => ids.has(id))) {
            members.push(candidate);
            remaining.delete(candidate);
          }
        }
      }
      if (members.length > 1) {
        members.sort((left, right) => (
          (finite(right?.automatic_research_pc_assessment?.log10_pc) ? right.automatic_research_pc_assessment.log10_pc : -Infinity)
            - (finite(left?.automatic_research_pc_assessment?.log10_pc) ? left.automatic_research_pc_assessment.log10_pc : -Infinity)
          || (finite(left?.automatic_research_pc_assessment?.miss_sigma_ratio) ? left.automatic_research_pc_assessment.miss_sigma_ratio : Infinity)
            - (finite(right?.automatic_research_pc_assessment?.miss_sigma_ratio) ? right.automatic_research_pc_assessment.miss_sigma_ratio : Infinity)
          || String(left?.id || "").localeCompare(String(right?.id || ""))
        ));
        const objectIds = new Set(members.flatMap((event) => [event?.primary?.id, event?.secondary?.id]).filter(Boolean));
        groups.push({ representative: members[0], members, coLocatedObjectCount: Math.max(0, objectIds.size - 2) });
      }
    }
  }
  return groups;
}

export function researchPcCatalogSummary(events = []) {
  const total = events.length;
  const valid = events.filter((event) => event?.physics_result?.status === "valid" && event?.physics_result?.tca_status === "valid");
  const logs = valid.map((event) => event?.automatic_research_pc_assessment?.log10_pc).filter(finite);
  const reasons = valid.filter((event) => {
    const assessment = event?.automatic_research_pc_assessment;
    return typeof assessment?.reason_code === "string" && assessment.reason_code.length > 0
      || Array.isArray(assessment?.reason_codes) && assessment.reason_codes.length > 0;
  }).length;
  const withPcOrReason = valid.filter((event) => Number.isFinite(event?.automatic_research_pc_assessment?.log10_pc)
    || typeof event?.automatic_research_pc_assessment?.reason_code === "string" && event.automatic_research_pc_assessment.reason_code.length > 0
    || Array.isArray(event?.automatic_research_pc_assessment?.reason_codes) && event.automatic_research_pc_assessment.reason_codes.length > 0).length;
  const boundaries = events.filter((event) => event?.physics_result?.tca_status === "boundary");
  const bins = [
    { label: "< -30", min: -Infinity, max: -30 },
    { label: "-30 to -20", min: -30, max: -20 },
    { label: "-20 to -12", min: -20, max: -12 },
    { label: "-12 to -7", min: -12, max: -7 },
    { label: "-7 to -4", min: -7, max: -4 },
    { label: "≥ -4", min: -4, max: Infinity },
  ].map((bin) => ({ ...bin, count: logs.filter((value) => value >= bin.min && value < bin.max).length }));
  const classCounts = { High: 0, Medium: 0, Low: 0, Unclassified: 0 };
  const classRawEventCounts = { High: 0, Medium: 0, Low: 0, Unclassified: 0 };
  const detectedGroups = groupCoLocatedEvents(valid);
  const groupedIds = new Set(detectedGroups.flatMap((group) => group.members.map((event) => event.id)));
  const encounterUnits = [
    ...detectedGroups,
    ...valid.filter((event) => !groupedIds.has(event.id)).map((event) => ({ representative: event, members: [event] })),
  ];
  const classOrder = { High: 3, Medium: 2, Low: 1, Unclassified: 0 };
  for (const group of encounterUnits) {
    const groupClass = group.members.map((event) => {
      const name = event?.automatic_research_pc_assessment?.risk_assessment?.final_risk_class;
      return Object.hasOwn(classOrder, name) ? name : "Unclassified";
    }).sort((left, right) => classOrder[right] - classOrder[left])[0] || "Unclassified";
    classCounts[groupClass] += 1;
    classRawEventCounts[groupClass] += group.members.length;
  }
  return {
    total, valid: valid.length, withResearchPc: logs.length, withReasonCode: reasons,
    withoutPcOrReason: valid.length - withPcOrReason,
    boundary: boundaries.length, histogram: bins, classCounts, classRawEventCounts,
    encounterCount: encounterUnits.length,
    encounterGroups: detectedGroups.map((group) => ({
      representativeEventId: group.representative.id,
      memberEventIds: group.members.map((event) => event.id),
      coLocatedObjectCount: group.coLocatedObjectCount,
    })),
  };
}
