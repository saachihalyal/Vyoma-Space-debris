export function referenceAssessmentMatchesIndependence(assessment, assumeIndependent) {
  const usedAssumption = assessment?.collision_probability?.independence_assumption_authorized;
  return typeof usedAssumption === "boolean" && usedAssumption === assumeIndependent;
}
