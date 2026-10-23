"""Premier League 2015/16 calibration data. GENERATED, do not edit by hand.

Produced by tools/calibrate_from_statsbomb.py from StatsBomb Open Data
(https://github.com/statsbomb/open-data). Aggregated statistics only, no raw events.
"""

SOURCE = "StatsBomb Open Data - Premier League 2015/16 (380 matches)"

FORMATIONS = {
 "4231": [
  "GK",
  "RB",
  "RCB",
  "LCB",
  "LB",
  "RDM",
  "LDM",
  "RW",
  "CAM",
  "LW",
  "ST"
 ],
 "442": [
  "GK",
  "RB",
  "RCB",
  "LCB",
  "LB",
  "RDM",
  "LDM",
  "RM",
  "LM",
  "RCF",
  "LCF"
 ],
 "433": [
  "GK",
  "RB",
  "RCB",
  "LCB",
  "LB",
  "CDM",
  "RCM",
  "LCM",
  "RW",
  "LW",
  "ST"
 ],
 "4411": [
  "GK",
  "RB",
  "RCB",
  "LCB",
  "LB",
  "RDM",
  "LDM",
  "RM",
  "LM",
  "CAM",
  "ST"
 ],
 "4141": [
  "GK",
  "RB",
  "RCB",
  "LCB",
  "LB",
  "CDM",
  "RM",
  "RCM",
  "LCM",
  "LM",
  "ST"
 ],
 "41212": [
  "GK",
  "RB",
  "RCB",
  "LCB",
  "LB",
  "CDM",
  "RCM",
  "LCM",
  "CAM",
  "RCF",
  "LCF"
 ],
 "451": [
  "GK",
  "RB",
  "RCB",
  "LCB",
  "LB",
  "CDM",
  "RM",
  "RCM",
  "LCM",
  "LM",
  "ST"
 ],
 "352": [
  "GK",
  "RCB",
  "CB",
  "LCB",
  "RWB",
  "LWB",
  "CDM",
  "RCM",
  "LCM",
  "RCF",
  "LCF"
 ],
 "343": [
  "GK",
  "RCB",
  "CB",
  "LCB",
  "RWB",
  "LWB",
  "RDM",
  "LDM",
  "RW",
  "LW",
  "ST"
 ],
 "3412": [
  "GK",
  "RCB",
  "CB",
  "LCB",
  "RWB",
  "LWB",
  "RDM",
  "LDM",
  "CAM",
  "RCF",
  "LCF"
 ],
 "4321": [
  "GK",
  "RB",
  "RCB",
  "LCB",
  "LB",
  "CDM",
  "RCM",
  "LCM",
  "RAM",
  "LAM",
  "ST"
 ],
 "3421": [
  "GK",
  "RCB",
  "CB",
  "LCB",
  "RWB",
  "LWB",
  "RDM",
  "LDM",
  "RAM",
  "LAM",
  "ST"
 ],
 "4222": [
  "GK",
  "RB",
  "RCB",
  "LCB",
  "LB",
  "RDM",
  "LDM",
  "RAM",
  "LAM",
  "RCF",
  "LCF"
 ]
}

FORMATION_WEIGHTS = {
 "4231": 0.5053,
 "442": 0.1579,
 "433": 0.0855,
 "4411": 0.0803,
 "4141": 0.0789,
 "41212": 0.0197,
 "451": 0.0171,
 "352": 0.0145,
 "343": 0.0118,
 "3412": 0.0105,
 "4321": 0.0092,
 "3421": 0.0079,
 "4222": 0.0013
}

TACTICAL_SHIFTS = {
 "per_team_match": 0.822,
 "formation_change_share": 0.304,
 "by_score_state": {
  "drawing": 0.346,
  "trailing": 0.402,
  "leading": 0.253
 },
 "minute_buckets": {
  "0": 0.021,
  "15": 0.035,
  "30": 0.04,
  "45": 0.256,
  "60": 0.302,
  "75": 0.318,
  "90": 0.027
 },
 "top_transitions": [
  [
   "4231",
   "442",
   25
  ],
  [
   "442",
   "4231",
   17
  ],
  [
   "433",
   "4231",
   10
  ],
  [
   "4411",
   "442",
   8
  ],
  [
   "4231",
   "433",
   7
  ],
  [
   "4141",
   "442",
   7
  ],
  [
   "4231",
   "4411",
   7
  ],
  [
   "4231",
   "41212",
   6
  ],
  [
   "433",
   "442",
   6
  ],
  [
   "442",
   "433",
   6
  ],
  [
   "4141",
   "4231",
   5
  ],
  [
   "451",
   "442",
   4
  ],
  [
   "4231",
   "352",
   4
  ],
  [
   "4321",
   "4231",
   4
  ],
  [
   "442",
   "4411",
   4
  ],
  [
   "442",
   "451",
   4
  ],
  [
   "4231",
   "4141",
   4
  ],
  [
   "3421",
   "442",
   3
  ],
  [
   "4231",
   "451",
   3
  ],
  [
   "433",
   "3421",
   2
  ],
  [
   "4231",
   "343",
   2
  ],
  [
   "4411",
   "4141",
   2
  ],
  [
   "433",
   "4141",
   2
  ],
  [
   "343",
   "442",
   2
  ],
  [
   "451",
   "4141",
   2
  ]
 ]
}

SUBSTITUTIONS = {
 "per_team_match": 2.775,
 "minute_by_order": {
  "1": [
   41,
   45,
   60,
   68,
   74
  ],
  "2": [
   57,
   64,
   72,
   78,
   84
  ],
  "3": [
   71,
   76,
   82,
   86,
   90
  ]
 },
 "by_score_state": {
  "drawing": 0.324,
  "trailing": 0.344,
  "leading": 0.332
 },
 "injury_share_before_45": 0.04
}

SHOTS = {
 "assist_type": {
  "ground_pass": 0.3885,
  "no_assist": 0.2691,
  "cross": 0.1158,
  "set_piece": 0.1102,
  "high_pass": 0.0645,
  "through_ball": 0.0334,
  "cut_back": 0.0184
 },
 "shot_type": {
  "Open Play": 0.9502,
  "Free Kick": 0.0405,
  "Penalty": 0.0092,
  "Corner": 0.0001
 },
 "distance_quantiles": [
  8.4,
  12.3,
  18.9,
  25.4,
  29.8
 ],
 "by_assist": {
  "cross": {
   "n": 1137,
   "band": {
    "0-12": 0.6245,
    "12-18": 0.3078,
    "18-25": 0.0668,
    "25+": 0.0009
   },
   "by_band": {
    "0-12": {
     "n": 710,
     "head": 0.631,
     "technique_foot": {
      "Normal": 0.3626,
      "Volley": 0.2939,
      "Half Volley": 0.2519,
      "Backheel": 0.0763,
      "Overhead Kick": 0.0153
     },
     "technique_head": {
      "Normal": 0.9754,
      "Diving Header": 0.0246
     },
     "first_time_head": 0.0022,
     "first_time_foot": 0.8473,
     "aerial_won_head": 0.5737,
     "one_on_one": 0.0915,
     "under_pressure": 0.4408
    },
    "12-18": {
     "n": 350,
     "head": 0.3114,
     "technique_foot": {
      "Normal": 0.444,
      "Volley": 0.2614,
      "Half Volley": 0.249,
      "Overhead Kick": 0.0415,
      "Backheel": 0.0041
     },
     "technique_head": {
      "Normal": 0.9358,
      "Diving Header": 0.0642
     },
     "first_time_head": 0.0092,
     "first_time_foot": 0.6556,
     "aerial_won_head": 0.5046,
     "one_on_one": 0.0229,
     "under_pressure": 0.2657
    },
    "18-25": {
     "n": 76,
     "head": 0.0132,
     "technique_foot": {
      "Normal": 0.5867,
      "Half Volley": 0.3067,
      "Volley": 0.0933,
      "Overhead Kick": 0.0133
     },
     "technique_head": {
      "Diving Header": 1.0
     },
     "first_time_head": 0.0,
     "first_time_foot": 0.5333,
     "aerial_won_head": 0.0,
     "one_on_one": 0.0,
     "under_pressure": 0.1053
    }
   }
  },
  "cut_back": {
   "n": 181,
   "band": {
    "0-12": 0.4144,
    "12-18": 0.3757,
    "18-25": 0.1934,
    "25+": 0.0166
   },
   "by_band": {
    "0-12": {
     "n": 75,
     "head": 0.0533,
     "technique_foot": {
      "Normal": 0.6761,
      "Half Volley": 0.2394,
      "Volley": 0.0704,
      "Backheel": 0.0141
     },
     "technique_head": {
      "Normal": 0.5,
      "Diving Header": 0.5
     },
     "first_time_head": 0.0,
     "first_time_foot": 0.9014,
     "aerial_won_head": 0.25,
     "one_on_one": 0.0,
     "under_pressure": 0.1733
    },
    "12-18": {
     "n": 68,
     "head": 0.0147,
     "technique_foot": {
      "Normal": 0.8209,
      "Half Volley": 0.1493,
      "Volley": 0.0299
     },
     "technique_head": {
      "Normal": 1.0
     },
     "first_time_head": 0.0,
     "first_time_foot": 0.7612,
     "aerial_won_head": 0.0,
     "one_on_one": 0.0,
     "under_pressure": 0.1176
    },
    "18-25": {
     "n": 35,
     "head": 0.0,
     "technique_foot": {
      "Normal": 0.9714,
      "Half Volley": 0.0286
     },
     "technique_head": {
      "Normal": 1.0
     },
     "first_time_head": 0.0,
     "first_time_foot": 0.6571,
     "aerial_won_head": 0.0,
     "one_on_one": 0.0,
     "under_pressure": 0.0857
    }
   }
  },
  "ground_pass": {
   "n": 3814,
   "band": {
    "18-25": 0.3865,
    "25+": 0.3797,
    "12-18": 0.1859,
    "0-12": 0.048
   },
   "by_band": {
    "0-12": {
     "n": 183,
     "head": 0.0656,
     "technique_foot": {
      "Normal": 0.655,
      "Half Volley": 0.2398,
      "Volley": 0.0702,
      "Lob": 0.0117,
      "Overhead Kick": 0.0117,
      "Backheel": 0.0117
     },
     "technique_head": {
      "Normal": 0.6667,
      "Diving Header": 0.3333
     },
     "first_time_head": 0.0,
     "first_time_foot": 0.6784,
     "aerial_won_head": 0.0833,
     "one_on_one": 0.1202,
     "under_pressure": 0.2186
    },
    "12-18": {
     "n": 709,
     "head": 0.0,
     "technique_foot": {
      "Normal": 0.8674,
      "Half Volley": 0.1058,
      "Volley": 0.0169,
      "Lob": 0.0056,
      "Backheel": 0.0028,
      "Overhead Kick": 0.0014
     },
     "technique_head": {
      "Normal": 1.0
     },
     "first_time_head": 0.0,
     "first_time_foot": 0.3512,
     "aerial_won_head": 0.0,
     "one_on_one": 0.079,
     "under_pressure": 0.2158
    },
    "18-25": {
     "n": 1474,
     "head": 0.0,
     "technique_foot": {
      "Normal": 0.9396,
      "Half Volley": 0.0488,
      "Volley": 0.0095,
      "Lob": 0.002
     },
     "technique_head": {
      "Normal": 1.0
     },
     "first_time_head": 0.0,
     "first_time_foot": 0.2388,
     "aerial_won_head": 0.0,
     "one_on_one": 0.0129,
     "under_pressure": 0.1513
    },
    "25+": {
     "n": 1448,
     "head": 0.0,
     "technique_foot": {
      "Normal": 0.9593,
      "Half Volley": 0.038,
      "Lob": 0.0021,
      "Volley": 0.0007
     },
     "technique_head": {
      "Normal": 1.0
     },
     "first_time_head": 0.0,
     "first_time_foot": 0.1291,
     "aerial_won_head": 0.0,
     "one_on_one": 0.0,
     "under_pressure": 0.107
    }
   }
  },
  "high_pass": {
   "n": 633,
   "band": {
    "12-18": 0.2986,
    "0-12": 0.2765,
    "18-25": 0.2607,
    "25+": 0.1643
   },
   "by_band": {
    "0-12": {
     "n": 175,
     "head": 0.6171,
     "technique_foot": {
      "Half Volley": 0.4179,
      "Volley": 0.2537,
      "Normal": 0.194,
      "Overhead Kick": 0.0896,
      "Lob": 0.0299,
      "Backheel": 0.0149
     },
     "technique_head": {
      "Normal": 0.9722,
      "Diving Header": 0.0278
     },
     "first_time_head": 0.0,
     "first_time_foot": 0.5522,
     "aerial_won_head": 0.4167,
     "one_on_one": 0.2514,
     "under_pressure": 0.3657
    },
    "12-18": {
     "n": 189,
     "head": 0.2698,
     "technique_foot": {
      "Normal": 0.4348,
      "Half Volley": 0.3333,
      "Volley": 0.1812,
      "Overhead Kick": 0.0435,
      "Lob": 0.0072
     },
     "technique_head": {
      "Normal": 0.9804,
      "Diving Header": 0.0196
     },
     "first_time_head": 0.0,
     "first_time_foot": 0.2754,
     "aerial_won_head": 0.5098,
     "one_on_one": 0.1481,
     "under_pressure": 0.3439
    },
    "18-25": {
     "n": 165,
     "head": 0.0242,
     "technique_foot": {
      "Normal": 0.5901,
      "Half Volley": 0.205,
      "Volley": 0.1491,
      "Overhead Kick": 0.0311,
      "Lob": 0.0248
     },
     "technique_head": {
      "Normal": 1.0
     },
     "first_time_head": 0.0,
     "first_time_foot": 0.2609,
     "aerial_won_head": 0.5,
     "one_on_one": 0.0303,
     "under_pressure": 0.1758
    },
    "25+": {
     "n": 104,
     "head": 0.0096,
     "technique_foot": {
      "Normal": 0.7087,
      "Half Volley": 0.2524,
      "Volley": 0.0291,
      "Lob": 0.0097
     },
     "technique_head": {
      "Diving Header": 1.0
     },
     "first_time_head": 0.0,
     "first_time_foot": 0.1165,
     "aerial_won_head": 0.0,
     "one_on_one": 0.0,
     "under_pressure": 0.0865
    }
   }
  },
  "no_assist": {
   "n": 2642,
   "band": {
    "25+": 0.3581,
    "18-25": 0.2967,
    "12-18": 0.1942,
    "0-12": 0.151
   },
   "by_band": {
    "0-12": {
     "n": 399,
     "head": 0.183,
     "technique_foot": {
      "Normal": 0.408,
      "Half Volley": 0.316,
      "Volley": 0.2086,
      "Overhead Kick": 0.0337,
      "Backheel": 0.0276,
      "Lob": 0.0061
     },
     "technique_head": {
      "Normal": 0.9726,
      "Diving Header": 0.0137,
      "Lob": 0.0137
     },
     "first_time_head": 0.0137,
     "first_time_foot": 0.6871,
     "aerial_won_head": 0.2877,
     "one_on_one": 0.0802,
     "under_pressure": 0.198
    },
    "12-18": {
     "n": 513,
     "head": 0.0351,
     "technique_foot": {
      "Normal": 0.5293,
      "Half Volley": 0.3091,
      "Volley": 0.1394,
      "Overhead Kick": 0.0182,
      "Lob": 0.004
     },
     "technique_head": {
      "Normal": 1.0
     },
     "first_time_head": 0.0,
     "first_time_foot": 0.5414,
     "aerial_won_head": 0.3333,
     "one_on_one": 0.0585,
     "under_pressure": 0.1774
    },
    "18-25": {
     "n": 784,
     "head": 0.0051,
     "technique_foot": {
      "Normal": 0.6,
      "Half Volley": 0.2551,
      "Volley": 0.1308,
      "Lob": 0.0103,
      "Overhead Kick": 0.0038
     },
     "technique_head": {
      "Normal": 1.0
     },
     "first_time_head": 0.0,
     "first_time_foot": 0.4167,
     "aerial_won_head": 0.5,
     "one_on_one": 0.0089,
     "under_pressure": 0.1339
    },
    "25+": {
     "n": 946,
     "head": 0.0011,
     "technique_foot": {
      "Normal": 0.7534,
      "Half Volley": 0.1788,
      "Volley": 0.0603,
      "Lob": 0.0074
     },
     "technique_head": {
      "Normal": 1.0
     },
     "first_time_head": 0.0,
     "first_time_foot": 0.2222,
     "aerial_won_head": 0.0,
     "one_on_one": 0.0021,
     "under_pressure": 0.0751
    }
   }
  },
  "set_piece": {
   "n": 1082,
   "band": {
    "0-12": 0.6673,
    "12-18": 0.1802,
    "25+": 0.0878,
    "18-25": 0.0647
   },
   "by_band": {
    "0-12": {
     "n": 722,
     "head": 0.8684,
     "technique_foot": {
      "Volley": 0.4842,
      "Half Volley": 0.2842,
      "Normal": 0.1474,
      "Backheel": 0.0737,
      "Overhead Kick": 0.0105
     },
     "technique_head": {
      "Normal": 0.9809,
      "Diving Header": 0.0191
     },
     "first_time_head": 0.0016,
     "first_time_foot": 0.8421,
     "aerial_won_head": 0.6794,
     "one_on_one": 0.0457,
     "under_pressure": 0.6219
    },
    "12-18": {
     "n": 195,
     "head": 0.6872,
     "technique_foot": {
      "Normal": 0.3607,
      "Half Volley": 0.2787,
      "Volley": 0.2787,
      "Overhead Kick": 0.0656,
      "Lob": 0.0164
     },
     "technique_head": {
      "Normal": 0.9851,
      "Diving Header": 0.0149
     },
     "first_time_head": 0.0,
     "first_time_foot": 0.5738,
     "aerial_won_head": 0.4851,
     "one_on_one": 0.0308,
     "under_pressure": 0.3846
    },
    "18-25": {
     "n": 70,
     "head": 0.0286,
     "technique_foot": {
      "Normal": 0.7353,
      "Half Volley": 0.1324,
      "Volley": 0.1176,
      "Lob": 0.0147
     },
     "technique_head": {
      "Normal": 1.0
     },
     "first_time_head": 0.0,
     "first_time_foot": 0.4853,
     "aerial_won_head": 0.0,
     "one_on_one": 0.0143,
     "under_pressure": 0.2286
    },
    "25+": {
     "n": 95,
     "head": 0.0,
     "technique_foot": {
      "Normal": 0.8737,
      "Half Volley": 0.1158,
      "Volley": 0.0105
     },
     "technique_head": {
      "Normal": 1.0
     },
     "first_time_head": 0.0,
     "first_time_foot": 0.2842,
     "aerial_won_head": 0.0,
     "one_on_one": 0.0,
     "under_pressure": 0.1158
    }
   }
  },
  "through_ball": {
   "n": 328,
   "band": {
    "12-18": 0.5427,
    "0-12": 0.2378,
    "18-25": 0.2043,
    "25+": 0.0152
   },
   "by_band": {
    "0-12": {
     "n": 78,
     "head": 0.1026,
     "technique_foot": {
      "Normal": 0.5286,
      "Half Volley": 0.3143,
      "Volley": 0.1286,
      "Lob": 0.0286
     },
     "technique_head": {
      "Normal": 0.875,
      "Diving Header": 0.125
     },
     "first_time_head": 0.0,
     "first_time_foot": 0.4143,
     "aerial_won_head": 0.25,
     "one_on_one": 0.359,
     "under_pressure": 0.1667
    },
    "12-18": {
     "n": 178,
     "head": 0.0056,
     "technique_foot": {
      "Normal": 0.7571,
      "Half Volley": 0.1243,
      "Lob": 0.0621,
      "Volley": 0.0565
     },
     "technique_head": {
      "Normal": 1.0
     },
     "first_time_head": 0.0,
     "first_time_foot": 0.4294,
     "aerial_won_head": 0.0,
     "one_on_one": 0.2809,
     "under_pressure": 0.191
    },
    "18-25": {
     "n": 67,
     "head": 0.0149,
     "technique_foot": {
      "Normal": 0.697,
      "Half Volley": 0.1667,
      "Lob": 0.1212,
      "Volley": 0.0152
     },
     "technique_head": {
      "Normal": 1.0
     },
     "first_time_head": 0.0,
     "first_time_foot": 0.5303,
     "aerial_won_head": 0.0,
     "one_on_one": 0.1343,
     "under_pressure": 0.209
    }
   }
  }
 },
 "lateral_q": {
  "cross|0-12": [
   0.34,
   1.7,
   3.5,
   5.4,
   8.4
  ],
  "cross|12-18": [
   0.7,
   2.92,
   5.6,
   8.77,
   13.06
  ],
  "cross|18-25": [
   1.35,
   4.5,
   6.95,
   13.42,
   15.93
  ],
  "cut_back|0-12": [
   0.57,
   2.35,
   3.6,
   5.95,
   8.06
  ],
  "cut_back|12-18": [
   1.33,
   2.87,
   6.1,
   9.35,
   12.5
  ],
  "cut_back|18-25": [
   6.46,
   10.05,
   12.5,
   15.4,
   17.57
  ],
  "ground_pass|0-12": [
   0.4,
   1.6,
   3.2,
   5.85,
   10.25
  ],
  "ground_pass|12-18": [
   1.0,
   4.8,
   9.7,
   12.1,
   14.56
  ],
  "ground_pass|18-25": [
   1.0,
   5.2,
   10.6,
   14.2,
   17.9
  ],
  "ground_pass|25+": [
   0.8,
   4.9,
   10.2,
   15.1,
   20.3
  ],
  "high_pass|0-12": [
   0.27,
   1.8,
   3.3,
   6.05,
   9.5
  ],
  "high_pass|12-18": [
   0.54,
   4.5,
   9.0,
   12.3,
   14.86
  ],
  "high_pass|18-25": [
   1.82,
   8.2,
   12.2,
   15.2,
   18.08
  ],
  "high_pass|25+": [
   1.8,
   6.37,
   13.05,
   17.72,
   21.12
  ],
  "no_assist|0-12": [
   0.3,
   1.75,
   3.7,
   6.3,
   9.51
  ],
  "no_assist|12-18": [
   0.8,
   4.1,
   7.4,
   11.0,
   13.5
  ],
  "no_assist|18-25": [
   0.9,
   4.2,
   8.2,
   12.3,
   17.08
  ],
  "no_assist|25+": [
   0.8,
   4.6,
   9.2,
   14.5,
   21.48
  ],
  "set_piece|0-12": [
   0.3,
   1.6,
   3.7,
   5.9,
   8.99
  ],
  "set_piece|12-18": [
   0.5,
   2.9,
   6.1,
   9.75,
   12.99
  ],
  "set_piece|18-25": [
   0.67,
   4.25,
   10.55,
   15.18,
   17.55
  ],
  "set_piece|25+": [
   1.17,
   5.25,
   13.0,
   17.85,
   21.38
  ],
  "through_ball|0-12": [
   0.59,
   3.4,
   5.95,
   8.47,
   10.41
  ],
  "through_ball|12-18": [
   3.09,
   6.2,
   9.5,
   11.68,
   14.0
  ],
  "through_ball|18-25": [
   2.05,
   6.65,
   9.9,
   14.05,
   16.2
  ],
  "any|0-12": [
   0.3,
   1.7,
   3.6,
   5.9,
   9.29
  ],
  "any|12-18": [
   0.8,
   4.1,
   7.9,
   11.3,
   14.1
  ],
  "any|18-25": [
   1.0,
   5.0,
   9.9,
   13.8,
   17.7
  ],
  "any|25+": [
   0.8,
   4.82,
   10.0,
   15.1,
   20.7
  ]
 },
 "distance_q": {
  "cross|0-12": [
   4.96,
   7.15,
   8.87,
   10.47,
   11.57
  ],
  "cross|12-18": [
   12.14,
   12.92,
   14.02,
   15.34,
   17.31
  ],
  "cross|18-25": [
   18.11,
   18.98,
   19.88,
   21.25,
   23.84
  ],
  "cut_back|0-12": [
   6.71,
   8.63,
   9.84,
   10.76,
   11.73
  ],
  "cut_back|12-18": [
   12.35,
   13.49,
   14.92,
   15.75,
   17.63
  ],
  "cut_back|18-25": [
   18.08,
   18.81,
   19.88,
   21.25,
   23.38
  ],
  "ground_pass|0-12": [
   4.13,
   8.1,
   9.44,
   11.05,
   11.81
  ],
  "ground_pass|12-18": [
   12.74,
   14.44,
   15.85,
   16.96,
   17.78
  ],
  "ground_pass|18-25": [
   18.38,
   19.93,
   21.73,
   23.43,
   24.67
  ],
  "ground_pass|25+": [
   25.33,
   26.61,
   28.52,
   31.1,
   36.07
  ],
  "high_pass|0-12": [
   4.94,
   7.16,
   8.91,
   10.73,
   11.8
  ],
  "high_pass|12-18": [
   12.28,
   13.64,
   15.21,
   16.54,
   17.72
  ],
  "high_pass|18-25": [
   18.23,
   19.39,
   20.92,
   22.97,
   24.41
  ],
  "high_pass|25+": [
   25.25,
   26.69,
   28.33,
   30.66,
   37.26
  ],
  "no_assist|0-12": [
   3.3,
   6.23,
   8.51,
   10.38,
   11.7
  ],
  "no_assist|12-18": [
   12.35,
   13.62,
   15.24,
   16.67,
   17.65
  ],
  "no_assist|18-25": [
   18.4,
   19.82,
   21.71,
   23.41,
   24.63
  ],
  "no_assist|25+": [
   25.38,
   26.85,
   28.7,
   31.36,
   36.38
  ],
  "set_piece|0-12": [
   4.93,
   7.42,
   8.78,
   10.34,
   11.58
  ],
  "set_piece|12-18": [
   12.1,
   12.61,
   13.81,
   15.14,
   17.16
  ],
  "set_piece|18-25": [
   18.34,
   19.75,
   21.24,
   22.72,
   24.05
  ],
  "set_piece|25+": [
   25.95,
   28.23,
   29.97,
   32.71,
   36.17
  ],
  "through_ball|0-12": [
   5.98,
   9.02,
   10.61,
   11.41,
   11.83
  ],
  "through_ball|12-18": [
   12.18,
   13.29,
   15.04,
   16.46,
   17.64
  ],
  "through_ball|18-25": [
   18.12,
   18.54,
   19.83,
   21.19,
   24.07
  ],
  "any|0-12": [
   4.61,
   7.2,
   8.96,
   10.58,
   11.7
  ],
  "any|12-18": [
   12.28,
   13.47,
   15.05,
   16.56,
   17.71
  ],
  "any|18-25": [
   18.31,
   19.74,
   21.48,
   23.3,
   24.63
  ],
  "any|25+": [
   25.35,
   26.72,
   28.66,
   31.26,
   36.25
  ]
 }
}

FREEZE_FRAME_TARGETS = {
 "overall": {
  "n": 9804,
  "cone": {
   "0": 0.4628,
   "1": 0.3561,
   "2": 0.1138,
   "3": 0.043,
   "4": 0.0243
  },
  "nearest_q": [
   0.91,
   1.4,
   2.33,
   3.77,
   5.76
  ],
  "gk_q": [
   1.42,
   2.09,
   3.09,
   4.25,
   5.73
  ]
 },
 "by_assist": {
  "cross": {
   "n": 1137,
   "cone": {
    "0": 0.6113,
    "1": 0.343,
    "2": 0.0431,
    "3": 0.0026
   },
   "nearest_q": [
    0.71,
    0.92,
    1.6,
    2.75,
    4.18
   ],
   "gk_q": [
    1.34,
    1.86,
    2.64,
    3.44,
    4.24
   ]
  },
  "cut_back": {
   "n": 180,
   "cone": {
    "0": 0.3,
    "1": 0.5389,
    "2": 0.1444,
    "3": 0.0111,
    "4": 0.0056
   },
   "nearest_q": [
    1.04,
    1.71,
    2.56,
    3.65,
    5.05
   ],
   "gk_q": [
    1.74,
    2.47,
    3.2,
    3.82,
    4.52
   ]
  },
  "ground_pass": {
   "n": 3811,
   "cone": {
    "0": 0.4865,
    "1": 0.4133,
    "2": 0.085,
    "3": 0.0126,
    "4": 0.0026
   },
   "nearest_q": [
    1.2,
    1.7,
    2.55,
    3.78,
    5.19
   ],
   "gk_q": [
    1.79,
    2.58,
    3.55,
    4.53,
    5.78
   ]
  },
  "high_pass": {
   "n": 633,
   "cone": {
    "0": 0.6698,
    "1": 0.2701,
    "2": 0.0411,
    "3": 0.0126,
    "4": 0.0063
   },
   "nearest_q": [
    0.85,
    1.22,
    2.0,
    3.09,
    4.72
   ],
   "gk_q": [
    1.71,
    2.4,
    3.41,
    4.53,
    5.98
   ]
  },
  "no_assist": {
   "n": 2635,
   "cone": {
    "0": 0.3214,
    "1": 0.3306,
    "2": 0.1803,
    "3": 0.0994,
    "4": 0.0683
   },
   "nearest_q": [
    1.22,
    1.88,
    3.04,
    5.32,
    9.4
   ],
   "gk_q": [
    1.39,
    1.89,
    2.77,
    3.98,
    5.63
   ]
  },
  "set_piece": {
   "n": 1081,
   "cone": {
    "0": 0.3247,
    "1": 0.3441,
    "2": 0.1998,
    "3": 0.0916,
    "4": 0.0398
   },
   "nearest_q": [
    0.58,
    0.81,
    1.12,
    1.84,
    3.48
   ],
   "gk_q": [
    0.99,
    1.39,
    2.04,
    2.87,
    3.83
   ]
  },
  "through_ball": {
   "n": 327,
   "cone": {
    "0": 0.9541,
    "1": 0.0459
   },
   "nearest_q": [
    0.98,
    1.41,
    2.28,
    3.54,
    5.27
   ],
   "gk_q": [
    3.71,
    4.87,
    6.75,
    9.31,
    11.33
   ]
  }
 },
 "by_band": {
  "0-12": {
   "n": 2338,
   "cone": {
    "0": 0.5565,
    "1": 0.3003,
    "2": 0.0941,
    "3": 0.0351,
    "4": 0.0141
   },
   "nearest_q": [
    0.63,
    0.86,
    1.3,
    2.23,
    3.49
   ],
   "gk_q": [
    1.12,
    1.58,
    2.46,
    3.54,
    5.28
   ]
  },
  "12-18": {
   "n": 2201,
   "cone": {
    "0": 0.5634,
    "1": 0.3021,
    "2": 0.0931,
    "3": 0.0309,
    "4": 0.0104
   },
   "nearest_q": [
    0.92,
    1.34,
    2.0,
    3.13,
    4.43
   ],
   "gk_q": [
    1.84,
    2.64,
    3.7,
    5.04,
    7.5
   ]
  },
  "18-25": {
   "n": 2668,
   "cone": {
    "0": 0.4292,
    "1": 0.3891,
    "2": 0.1079,
    "3": 0.042,
    "4": 0.0319
   },
   "nearest_q": [
    1.27,
    1.71,
    2.55,
    3.71,
    5.38
   ],
   "gk_q": [
    1.79,
    2.62,
    3.54,
    4.46,
    5.64
   ]
  },
  "25+": {
   "n": 2597,
   "cone": {
    "0": 0.3277,
    "1": 0.4182,
    "2": 0.1552,
    "3": 0.0616,
    "4": 0.0374
   },
   "nearest_q": [
    1.58,
    2.39,
    3.68,
    5.66,
    9.3
   ],
   "gk_q": [
    1.39,
    1.89,
    2.66,
    3.72,
    4.8
   ]
  }
 },
 "cone_by_assist_band": {
  "cross|0-12": {
   "0": 0.707,
   "1": 0.2817,
   "2": 0.0113
  },
  "cross|12-18": {
   "0": 0.48,
   "1": 0.4257,
   "2": 0.0914,
   "3": 0.0029
  },
  "cross|18-25": {
   "0": 0.3289,
   "1": 0.5395,
   "2": 0.1053,
   "3": 0.0263
  },
  "cut_back|0-12": {
   "0": 0.3919,
   "1": 0.5135,
   "2": 0.0811,
   "3": 0.0135
  },
  "cut_back|12-18": {
   "0": 0.25,
   "1": 0.5294,
   "2": 0.1912,
   "3": 0.0147,
   "4": 0.0147
  },
  "cut_back|18-25": {
   "0": 0.2,
   "1": 0.6,
   "2": 0.2
  },
  "ground_pass|0-12": {
   "0": 0.6612,
   "1": 0.2568,
   "2": 0.0656,
   "3": 0.0055,
   "4": 0.0109
  },
  "ground_pass|12-18": {
   "0": 0.6389,
   "1": 0.3004,
   "2": 0.0465,
   "3": 0.0113,
   "4": 0.0028
  },
  "ground_pass|18-25": {
   "0": 0.4861,
   "1": 0.4134,
   "2": 0.0815,
   "3": 0.017,
   "4": 0.002
  },
  "ground_pass|25+": {
   "0": 0.39,
   "1": 0.4882,
   "2": 0.11,
   "3": 0.0097,
   "4": 0.0021
  },
  "high_pass|0-12": {
   "0": 0.7314,
   "1": 0.1829,
   "2": 0.0571,
   "3": 0.0171,
   "4": 0.0114
  },
  "high_pass|12-18": {
   "0": 0.7513,
   "1": 0.2011,
   "2": 0.0317,
   "3": 0.0159
  },
  "high_pass|18-25": {
   "0": 0.5636,
   "1": 0.3697,
   "2": 0.0424,
   "3": 0.0121,
   "4": 0.0121
  },
  "high_pass|25+": {
   "0": 0.5865,
   "1": 0.3846,
   "2": 0.0288
  },
  "no_assist|0-12": {
   "0": 0.5377,
   "1": 0.3015,
   "2": 0.0854,
   "3": 0.0553,
   "4": 0.0201
  },
  "no_assist|12-18": {
   "0": 0.4219,
   "1": 0.3359,
   "2": 0.1602,
   "3": 0.0586,
   "4": 0.0234
  },
  "no_assist|18-25": {
   "0": 0.2826,
   "1": 0.3581,
   "2": 0.1765,
   "3": 0.0921,
   "4": 0.0908
  },
  "no_assist|25+": {
   "0": 0.2078,
   "1": 0.3171,
   "2": 0.2344,
   "3": 0.1463,
   "4": 0.0944
  },
  "set_piece|0-12": {
   "0": 0.3273,
   "1": 0.3592,
   "2": 0.208,
   "3": 0.0763,
   "4": 0.0291
  },
  "set_piece|12-18": {
   "0": 0.3692,
   "1": 0.2615,
   "2": 0.2,
   "3": 0.1282,
   "4": 0.041
  },
  "set_piece|18-25": {
   "0": 0.2714,
   "1": 0.3286,
   "2": 0.1143,
   "3": 0.1571,
   "4": 0.1286
  },
  "set_piece|25+": {
   "0": 0.2526,
   "1": 0.4105,
   "2": 0.2,
   "3": 0.0842,
   "4": 0.0526
  },
  "through_ball|0-12": {
   "0": 0.9221,
   "1": 0.0779
  },
  "through_ball|12-18": {
   "0": 0.9663,
   "1": 0.0337
  },
  "through_ball|18-25": {
   "0": 0.9552,
   "1": 0.0448
  }
 },
 "nearest_q_by_pressure_band": {
  "False|0-12": [
   0.73,
   1.3,
   1.93,
   2.89,
   5.1
  ],
  "False|12-18": [
   0.92,
   1.57,
   2.33,
   3.45,
   5.77
  ],
  "False|18-25": [
   1.12,
   1.9,
   2.73,
   3.91,
   7.21
  ],
  "False|25+": [
   1.36,
   2.61,
   3.95,
   6.04,
   10.41
  ],
  "True|0-12": [
   0.41,
   0.7,
   0.86,
   1.1,
   1.82
  ],
  "True|12-18": [
   0.57,
   0.91,
   1.3,
   1.77,
   2.92
  ],
  "True|18-25": [
   0.85,
   1.3,
   1.66,
   2.32,
   3.57
  ],
  "True|25+": [
   0.73,
   1.3,
   1.92,
   2.64,
   3.8
  ]
 },
 "gk_q_by_band": {
  "False|0-12": [
   0.86,
   1.53,
   2.4,
   3.44,
   6.46
  ],
  "False|12-18": [
   1.42,
   2.55,
   3.55,
   4.78,
   8.49
  ],
  "False|18-25": [
   1.49,
   2.62,
   3.52,
   4.42,
   6.5
  ],
  "False|25+": [
   1.12,
   1.89,
   2.66,
   3.72,
   5.51
  ],
  "True|0-12": [
   1.21,
   2.1,
   2.97,
   5.1,
   8.62
  ],
  "True|12-18": [
   3.2,
   4.52,
   6.17,
   9.39,
   13.12
  ],
  "True|18-25": [
   2.46,
   4.14,
   5.88,
   8.38,
   13.58
  ]
 },
 "nearest_q_under_pressure": [
  0.61,
  0.81,
  1.14,
  1.7,
  2.5
 ],
 "nearest_q_free": [
  1.22,
  1.8,
  2.77,
  4.24,
  6.49
 ],
 "gk_q_one_on_one": [
  1.8,
  2.83,
  4.52,
  7.03,
  10.76
 ]
}

OUTCOMES = {
 "non_goal": {
  "foot|0-12|0": {
   "Saved": 0.3803,
   "Off T": 0.3736,
   "Blocked": 0.1342,
   "Wayward": 0.0604,
   "Post": 0.038,
   "Saved Off Target": 0.0112,
   "Saved to Post": 0.0022
  },
  "foot|0-12|1": {
   "Blocked": 0.4721,
   "Off T": 0.2961,
   "Saved": 0.1588,
   "Wayward": 0.0515,
   "Post": 0.0172,
   "Saved to Post": 0.0043
  },
  "foot|0-12|2": {
   "Blocked": 0.4752,
   "Off T": 0.3564,
   "Saved": 0.0891,
   "Post": 0.0396,
   "Wayward": 0.0396
  },
  "foot|12-18|0": {
   "Saved": 0.4068,
   "Off T": 0.3239,
   "Blocked": 0.1727,
   "Wayward": 0.0455,
   "Post": 0.042,
   "Saved to Post": 0.0057,
   "Saved Off Target": 0.0034
  },
  "foot|12-18|1": {
   "Blocked": 0.5803,
   "Off T": 0.1985,
   "Saved": 0.155,
   "Wayward": 0.051,
   "Post": 0.0113,
   "Saved to Post": 0.0019,
   "Saved Off Target": 0.0019
  },
  "foot|12-18|2": {
   "Blocked": 0.545,
   "Off T": 0.2793,
   "Saved": 0.1036,
   "Wayward": 0.0541,
   "Post": 0.018
  },
  "foot|18-25|0": {
   "Off T": 0.3572,
   "Saved": 0.3442,
   "Blocked": 0.2512,
   "Wayward": 0.0223,
   "Post": 0.0186,
   "Saved Off Target": 0.0037,
   "Saved to Post": 0.0028
  },
  "foot|18-25|1": {
   "Blocked": 0.4964,
   "Off T": 0.2832,
   "Saved": 0.1797,
   "Wayward": 0.0254,
   "Post": 0.0081,
   "Saved Off Target": 0.0051,
   "Saved to Post": 0.002
  },
  "foot|18-25|2": {
   "Blocked": 0.5787,
   "Off T": 0.2681,
   "Saved": 0.1043,
   "Wayward": 0.0362,
   "Post": 0.0128
  },
  "foot|25+|0": {
   "Off T": 0.4711,
   "Saved": 0.2916,
   "Blocked": 0.2048,
   "Wayward": 0.0193,
   "Post": 0.006,
   "Saved Off Target": 0.006,
   "Saved to Post": 0.0012
  },
  "foot|25+|1": {
   "Blocked": 0.382,
   "Off T": 0.3605,
   "Saved": 0.2191,
   "Wayward": 0.0215,
   "Post": 0.0084,
   "Saved Off Target": 0.0066,
   "Saved to Post": 0.0019
  },
  "foot|25+|2": {
   "Blocked": 0.4173,
   "Off T": 0.3417,
   "Saved": 0.1937,
   "Wayward": 0.0236,
   "Post": 0.0189,
   "Saved Off Target": 0.0031,
   "Saved to Post": 0.0016
  },
  "head|0-12|0": {
   "Off T": 0.5543,
   "Saved": 0.2453,
   "Wayward": 0.0993,
   "Blocked": 0.0487,
   "Post": 0.0412,
   "Saved Off Target": 0.0056,
   "Saved to Post": 0.0056
  },
  "head|0-12|1": {
   "Off T": 0.4435,
   "Blocked": 0.2204,
   "Saved": 0.1989,
   "Wayward": 0.1048,
   "Post": 0.0188,
   "Saved Off Target": 0.0108,
   "Saved to Post": 0.0027
  },
  "head|0-12|2": {
   "Off T": 0.3805,
   "Blocked": 0.278,
   "Saved": 0.1805,
   "Wayward": 0.1415,
   "Post": 0.0146,
   "Saved Off Target": 0.0049
  },
  "head|12-18|0": {
   "Off T": 0.5345,
   "Saved": 0.2816,
   "Wayward": 0.092,
   "Blocked": 0.0517,
   "Post": 0.0172,
   "Saved Off Target": 0.0172,
   "Saved to Post": 0.0057
  },
  "head|12-18|1": {
   "Off T": 0.4684,
   "Saved": 0.2025,
   "Blocked": 0.1899,
   "Wayward": 0.0886,
   "Saved Off Target": 0.0253,
   "Post": 0.0253
  },
  "head|12-18|2": {
   "Blocked": 0.3529,
   "Off T": 0.2549,
   "Saved": 0.2353,
   "Wayward": 0.1569
  }
 },
 "non_goal_fallback": {
  "Off T": 0.3586,
  "Blocked": 0.3235,
  "Saved": 0.247,
  "Wayward": 0.0444,
  "Post": 0.019,
  "Saved Off Target": 0.0051,
  "Saved to Post": 0.0025
 },
 "penalty_conversion": 0.813,
 "penalty_non_goal": {
  "Saved": 0.5882,
  "Off T": 0.2353,
  "Wayward": 0.0588,
  "Saved to Post": 0.0588,
  "Post": 0.0588
 }
}

MATCH_TARGETS = {
 "passes": 485.02,
 "pass_accuracy": 76.24,
 "shots": 13.04,
 "shots_on_target": 4.24,
 "goals": 1.3,
 "xg_statsbomb": 1.28,
 "corners": 5.4,
 "fouls": 12.52,
 "yellow_cards": 1.58,
 "pressures": 151.84,
 "tackles": 20.32,
 "interceptions": 11.74,
 "dribbles": 18.05,
 "crosses": 12.56,
 "tactical_shifts": 0.82,
 "substitutions": 2.77,
 "home_draw_away_pct": {
  "H": 41.3,
  "A": 30.5,
  "D": 28.2
 },
 "goals_per_match": 2.7
}
