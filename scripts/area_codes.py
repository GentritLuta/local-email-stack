"""US area-code -> state (exact; each geographic NANP area code sits in one
state) and area-code -> metro label (for the common/major metros; on-the-fly
reporting only). Toll-free / non-geographic codes are intentionally absent so
callers SKIP them rather than guess.

All 13 area codes present in Aureon's data (317 463 910 614 719 512 720 980 216
330 336 219 602) are verified correct below.
"""

# state -> geographic area codes (current NANP). Inverted to AC_TO_STATE below.
_BY_STATE = {
    "AL": [205, 251, 256, 334, 659, 938],
    "AK": [907],
    "AZ": [480, 520, 602, 623, 928],
    "AR": [479, 501, 870],
    "CA": [209, 213, 279, 310, 323, 341, 350, 408, 415, 424, 442, 510, 530, 559,
           562, 619, 626, 628, 650, 657, 661, 669, 707, 714, 747, 760, 805, 818,
           820, 831, 840, 858, 909, 916, 925, 949, 951],
    "CO": [303, 719, 720, 970, 983],
    "CT": [203, 475, 860, 959],
    "DE": [302],
    "DC": [202],
    "FL": [239, 305, 321, 352, 386, 407, 448, 561, 656, 727, 754, 772, 786, 813,
           850, 863, 904, 941, 954],
    "GA": [229, 404, 470, 478, 678, 706, 762, 770, 912, 943],
    "HI": [808],
    "ID": [208, 986],
    "IL": [217, 224, 309, 312, 331, 447, 464, 618, 630, 708, 730, 773, 779, 815,
           847, 872],
    "IN": [219, 260, 317, 463, 574, 765, 812, 930],
    "IA": [319, 515, 563, 641, 712],
    "KS": [316, 620, 785, 913],
    "KY": [270, 364, 502, 606, 859],
    "LA": [225, 318, 337, 504, 985],
    "ME": [207],
    "MD": [240, 301, 410, 443, 667],
    "MA": [339, 351, 413, 508, 617, 774, 781, 857, 978],
    "MI": [231, 248, 269, 313, 517, 586, 616, 679, 734, 810, 906, 947, 989],
    "MN": [218, 320, 507, 612, 651, 763, 952],
    "MS": [228, 601, 662, 769],
    "MO": [314, 417, 557, 573, 636, 660, 816],
    "MT": [406],
    "NE": [308, 402, 531],
    "NV": [702, 725, 775],
    "NH": [603],
    "NJ": [201, 551, 609, 640, 732, 848, 856, 862, 908, 973],
    "NM": [505, 575],
    "NY": [212, 315, 329, 332, 347, 363, 516, 518, 585, 607, 631, 646, 680, 716,
           718, 838, 845, 914, 917, 929, 934],
    "NC": [252, 336, 704, 743, 828, 910, 919, 980, 984],
    "ND": [701],
    "OH": [216, 220, 234, 283, 326, 330, 380, 419, 440, 513, 567, 614, 740, 937],
    "OK": [405, 539, 572, 580, 918],
    "OR": [458, 503, 541, 971],
    "PA": [215, 223, 267, 272, 412, 445, 484, 570, 582, 610, 717, 724, 814, 835, 878],
    "RI": [401],
    "SC": [803, 839, 843, 854, 864],
    "SD": [605],
    "TN": [423, 615, 629, 731, 865, 901, 931],
    "TX": [210, 214, 254, 281, 325, 346, 361, 409, 430, 432, 469, 512, 682, 713,
           726, 737, 806, 817, 830, 832, 903, 915, 936, 940, 945, 956, 972, 979],
    "UT": [385, 435, 801],
    "VT": [802],
    "VA": [276, 434, 540, 571, 686, 703, 757, 804, 826, 948],
    "WA": [206, 253, 360, 425, 509, 564],
    "WV": [304, 681],
    "WI": [262, 274, 353, 414, 534, 608, 715, 920],
    "WY": [307],
}

AC_TO_STATE = {str(ac): st for st, acs in _BY_STATE.items() for ac in acs}

# area-code -> metro label (common + present-in-data; reporting only)
AC_TO_METRO = {
    "317": "Indianapolis", "463": "Indianapolis", "219": "Northwest Indiana",
    "260": "Fort Wayne", "574": "South Bend", "765": "Central Indiana",
    "812": "Southern Indiana", "930": "Southern Indiana",
    "614": "Columbus", "216": "Cleveland", "330": "Akron-Canton",
    "513": "Cincinnati", "419": "Toledo", "937": "Dayton",
    "910": "Fayetteville-Wilmington", "980": "Charlotte", "704": "Charlotte",
    "336": "Greensboro-Winston", "919": "Raleigh-Durham", "984": "Raleigh-Durham",
    "828": "Asheville", "252": "Eastern NC",
    "719": "Colorado Springs", "720": "Denver", "303": "Denver", "970": "Northern Colorado",
    "512": "Austin", "737": "Austin", "214": "Dallas", "469": "Dallas", "972": "Dallas",
    "713": "Houston", "281": "Houston", "832": "Houston", "210": "San Antonio",
    "602": "Phoenix", "623": "Phoenix", "480": "Phoenix", "520": "Tucson",
    "212": "New York", "646": "New York", "917": "New York", "718": "New York",
    "305": "Miami", "786": "Miami", "404": "Atlanta", "470": "Atlanta", "678": "Atlanta",
    "312": "Chicago", "773": "Chicago", "206": "Seattle", "415": "San Francisco",
    "213": "Los Angeles", "323": "Los Angeles", "702": "Las Vegas",
}


def state_for(area: str) -> str:
    return AC_TO_STATE.get((area or "").strip(), "")


def metro_for(area: str) -> str:
    return AC_TO_METRO.get((area or "").strip(), "")
