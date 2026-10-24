# NASA CARA reference CDM fixture

`nasa_cara_pc_reference.cdm` preserves the public numerical test case distributed by NASA's CARA Analysis Tools:

`DataFiles/PcTestCaseCDMs/000020580_conj_000002017_20230613_001923_20230608_063715.cdm`

Source: https://github.com/nasa/CARA_Analysis_Tools/blob/master/DataFiles/PcTestCaseCDMs/000020580_conj_000002017_20230613_001923_20230608_063715.cdm

The test makes a numeric comparison because this CDM supplies the TCA states, same-epoch covariance blocks, frame, positive HBR, and Foster method designation needed by ORION's supported 2D calculation. The fixture supplies separate object covariances but no cross-covariance; the reproduction therefore explicitly assumes independent object covariances, and reports that assumption. The CDM rounds source Pc to four significant digits, so comparison tolerance is `5e-9`, half a unit in the final printed digit. A reproducible standalone API/UI workflow loads this checked-in fixture and compares the calculated Pc with the source-reported value; it does not insert the record into live screening jobs. This comparison does not establish agreement with an independently executed operational NASA CARA calculation or validate ORION for operational use. The source-reported value is not an ORION result. The public repository lists NASA Open Source Software Agreements, but a separate data-specific license statement was not identified.
