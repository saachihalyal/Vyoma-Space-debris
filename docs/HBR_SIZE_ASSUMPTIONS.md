# Research Pc object-size HBR assumptions

These are project assumptions used only by the ORION prior-based research Pc
estimate when an exact normalized object name matches. The radius is an
equivalent-sphere radius in kilometres. It is not a measured or authenticated
hard-body radius, and no catalog dimensions are implied. Other objects use the
ESA Kelvins span prior (interpreted as a diameter and halved).

| Normalized name | Assumed radius (km) | Matching rationale |
| --- | ---: | --- |
| ISS | 0.050 | International Space Station whole-vehicle proxy |
| ISS (Zarya), ISS (Zvezda), ISS (Nauka) | 0.015 | Named station-module proxy |
| ISS (Poisk), ISS (Rassvet) | 0.010 | Named station-module proxy |
| ISS (Unity), ISS (Destiny), ISS (Harmony), ISS (Columbus), ISS (Kibo), ISS (Tranquility) | 0.012 | Named station-module proxy |
| Hubble Space Telescope | 0.007 | Large observatory proxy |
| Envisat | 0.013 | Large Earth-observation spacecraft proxy |
| Terra, Aqua | 0.012 | Large Earth-observation spacecraft proxy |

For each event, ORION adds the two assumed object radii to form HBR. A match is
reported in `hbr_provenance`; the record labels the source
`assumed_object_size_override`. This is a sensitivity assumption, not an
improvement in the event's covariance knowledge or a validation result.
