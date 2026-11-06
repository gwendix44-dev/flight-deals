"""Aéroports d'origine et destinations hors Europe.

Format destinations : code -> (ville, pays ISO, lat, lon, [aéroports réels pour les codes "ville"]).
Ajoute librement des lignes : une destination absente de cette table est ignorée.
"""

ORIGINS = {
    "NTE": ("Nantes", 47.153, -1.611),
    "CDG": ("Paris CDG", 49.013, 2.550),
    "ORY": ("Paris Orly", 48.723, 2.379),
    "LHR": ("Londres Heathrow", 51.470, -0.454),
    "MAD": ("Madrid", 40.494, -3.567),
    "FCO": ("Rome", 41.800, 12.250),
    "LIS": ("Lisbonne", 38.774, -9.134),
    "DUB": ("Dublin", 53.421, -6.270),
    "AMS": ("Amsterdam", 52.310, 4.768),
    "FRA": ("Francfort", 50.033, 8.571),
}

# Mots-clés de villes d'origine, pour lire les flux de bons plans.
ORIGIN_KEYWORDS = {
    "paris": "CDG", "nantes": "NTE", "london": "LHR", "londres": "LHR",
    "madrid": "MAD", "rome": "FCO", "lisbon": "LIS", "lisbonne": "LIS",
    "dublin": "DUB", "amsterdam": "AMS", "frankfurt": "FRA", "francfort": "FRA",
}

DESTINATIONS = {
    # Asie
    "TYO": ("Tokyo", "JP", 35.55, 139.78, ["HND", "NRT"]),
    "OSA": ("Osaka", "JP", 34.43, 135.24, ["KIX", "ITM"]),
    "BKK": ("Bangkok", "TH", 13.69, 100.75, []),
    "HKT": ("Phuket", "TH", 8.11, 98.31, []),
    "CNX": ("Chiang Mai", "TH", 18.77, 98.96, []),
    "SGN": ("Hô-Chi-Minh-Ville", "VN", 10.82, 106.65, []),
    "HAN": ("Hanoï", "VN", 21.22, 105.81, []),
    "DPS": ("Bali", "ID", -8.75, 115.17, []),
    "JKT": ("Jakarta", "ID", -6.13, 106.66, ["CGK"]),
    "KUL": ("Kuala Lumpur", "MY", 2.75, 101.71, []),
    "SIN": ("Singapour", "SG", 1.36, 103.99, []),
    "MNL": ("Manille", "PH", 14.51, 121.02, []),
    "CEB": ("Cebu", "PH", 10.31, 123.98, []),
    "PNH": ("Phnom Penh", "KH", 11.55, 104.84, []),
    "REP": ("Siem Reap", "KH", 13.41, 103.81, []),
    "DEL": ("Delhi", "IN", 28.56, 77.10, []),
    "BOM": ("Mumbai", "IN", 19.09, 72.87, []),
    "GOI": ("Goa", "IN", 15.38, 73.83, []),
    "BLR": ("Bangalore", "IN", 13.20, 77.71, []),
    "KTM": ("Katmandou", "NP", 27.70, 85.36, []),
    "CMB": ("Colombo", "LK", 7.18, 79.88, []),
    "SEL": ("Séoul", "KR", 37.46, 126.44, ["ICN", "GMP"]),
    "TPE": ("Taipei", "TW", 25.08, 121.23, []),
    "HKG": ("Hong Kong", "HK", 22.31, 113.91, []),
    "BJS": ("Pékin", "CN", 40.08, 116.58, ["PEK", "PKX"]),
    "SHA": ("Shanghai", "CN", 31.14, 121.81, ["PVG", "SHA"]),
    "CAN": ("Canton", "CN", 23.39, 113.30, []),
    "DXB": ("Dubaï", "AE", 25.25, 55.36, []),
    "AUH": ("Abou Dabi", "AE", 24.43, 54.65, []),
    "DOH": ("Doha", "QA", 25.27, 51.61, []),
    "AMM": ("Amman", "JO", 31.72, 35.99, []),
    "TLV": ("Tel Aviv", "IL", 32.01, 34.89, []),
    "TAS": ("Tachkent", "UZ", 41.26, 69.28, []),
    "MLE": ("Malé", "MV", 4.19, 73.53, []),
    # Afrique / océan Indien
    "RAK": ("Marrakech", "MA", 31.61, -8.04, []),
    "CMN": ("Casablanca", "MA", 33.37, -7.59, []),
    "TUN": ("Tunis", "TN", 36.85, 10.23, []),
    "CAI": ("Le Caire", "EG", 30.12, 31.41, []),
    "HRG": ("Hurghada", "EG", 27.18, 33.80, []),
    "DKR": ("Dakar", "SN", 14.67, -17.07, ["DSS"]),
    "ACC": ("Accra", "GH", 5.61, -0.17, []),
    "ADD": ("Addis-Abeba", "ET", 8.98, 38.80, []),
    "NBO": ("Nairobi", "KE", -1.32, 36.93, []),
    "ZNZ": ("Zanzibar", "TZ", -6.22, 39.22, []),
    "JRO": ("Kilimandjaro", "TZ", -3.43, 37.07, []),
    "CPT": ("Le Cap", "ZA", -33.97, 18.60, []),
    "JNB": ("Johannesburg", "ZA", -26.14, 28.25, []),
    "MRU": ("Île Maurice", "MU", -20.43, 57.68, []),
    "TNR": ("Antananarivo", "MG", -18.80, 47.48, []),
    "RUN": ("La Réunion", "RE", -20.89, 55.51, []),
    "SID": ("Cap-Vert (Sal)", "CV", 16.74, -22.95, []),
    # Amériques
    "NYC": ("New York", "US", 40.64, -73.78, ["JFK", "EWR", "LGA"]),
    "BOS": ("Boston", "US", 42.36, -71.01, []),
    "MIA": ("Miami", "US", 25.79, -80.29, []),
    "LAX": ("Los Angeles", "US", 33.94, -118.41, []),
    "SFO": ("San Francisco", "US", 37.62, -122.38, []),
    "YMQ": ("Montréal", "CA", 45.47, -73.74, ["YUL"]),
    "YTO": ("Toronto", "CA", 43.68, -79.63, ["YYZ"]),
    "YVR": ("Vancouver", "CA", 49.19, -123.18, []),
    "MEX": ("Mexico", "MX", 19.44, -99.07, []),
    "CUN": ("Cancún", "MX", 21.04, -86.87, []),
    "BOG": ("Bogotá", "CO", 4.70, -74.15, []),
    "MDE": ("Medellín", "CO", 6.17, -75.43, []),
    "LIM": ("Lima", "PE", -12.02, -77.11, []),
    "CUZ": ("Cusco", "PE", -13.54, -71.94, []),
    "SCL": ("Santiago", "CL", -33.39, -70.79, []),
    "BUE": ("Buenos Aires", "AR", -34.82, -58.54, ["EZE", "AEP"]),
    "RIO": ("Rio de Janeiro", "BR", -22.81, -43.25, ["GIG", "SDU"]),
    "SAO": ("São Paulo", "BR", -23.43, -46.47, ["GRU", "CGH"]),
    "UIO": ("Quito", "EC", -0.13, -78.36, []),
    "HAV": ("La Havane", "CU", 22.99, -82.41, []),
    "PUJ": ("Punta Cana", "DO", 18.57, -68.36, []),
    "SJO": ("San José", "CR", 9.99, -84.21, []),
    "PTY": ("Panama", "PA", 9.07, -79.38, []),
    "LPB": ("La Paz", "BO", -16.51, -68.19, []),
    "FDF": ("Martinique", "MQ", 14.59, -61.00, []),
    "PTP": ("Guadeloupe", "GP", 16.27, -61.53, []),
    # Océanie
    "SYD": ("Sydney", "AU", -33.95, 151.18, []),
    "MEL": ("Melbourne", "AU", -37.67, 144.84, []),
    "AKL": ("Auckland", "NZ", -37.01, 174.79, []),
}

# Mots-clés pour reconnaître une destination dans le titre d'un bon plan.
DEST_KEYWORDS = {}
for _code, (_city, _cc, *_rest) in DESTINATIONS.items():
    DEST_KEYWORDS[_city.lower()] = _code
DEST_KEYWORDS.update({
    "tokyo": "TYO", "japan": "TYO", "japon": "TYO", "osaka": "OSA", "bangkok": "BKK",
    "thailand": "BKK", "thaïlande": "BKK", "bali": "DPS", "indonesia": "DPS",
    "vietnam": "SGN", "singapore": "SIN", "seoul": "SEL", "new york": "NYC",
    "los angeles": "LAX", "san francisco": "SFO", "montreal": "YMQ", "toronto": "YTO",
    "mexico city": "MEX", "buenos aires": "BUE", "rio de janeiro": "RIO",
    "sao paulo": "SAO", "dubai": "DXB", "cape town": "CPT", "mauritius": "MRU",
    "sydney": "SYD", "melbourne": "MEL", "auckland": "AKL", "new zealand": "AKL",
    "marrakech": "RAK", "marrakesh": "RAK", "cairo": "CAI", "kathmandu": "KTM",
    "delhi": "DEL", "mumbai": "BOM", "colombo": "CMB", "hong kong": "HKG",
    "beijing": "BJS", "shanghai": "SHA", "taipei": "TPE", "manila": "MNL",
    "cancun": "CUN", "lima": "LIM", "bogota": "BOG", "santiago": "SCL",
    "havana": "HAV", "punta cana": "PUJ", "zanzibar": "ZNZ", "nairobi": "NBO",
})


# Hubs d'escale pour les montages à billets séparés.
# code -> (ville, pays, lat, lon, décalage UTC (heure standard), [aéroports])
HUBS = {
    "LIS": ("Lisbonne", "PT", 38.774, -9.134, 0, ["LIS"]),
    "OPO": ("Porto", "PT", 41.242, -8.678, 0, ["OPO"]),
    "MAD": ("Madrid", "ES", 40.494, -3.567, 1, ["MAD"]),
    "BCN": ("Barcelone", "ES", 41.297, 2.078, 1, ["BCN"]),
    "DUB": ("Dublin", "IE", 53.421, -6.270, 0, ["DUB"]),
    "LON": ("Londres", "GB", 51.470, -0.454, 0, ["LHR", "LGW", "STN", "LTN"]),
    "ROM": ("Rome", "IT", 41.800, 12.250, 1, ["FCO", "CIA"]),
    "ATH": ("Athènes", "GR", 37.936, 23.945, 2, ["ATH"]),
    "BUD": ("Budapest", "HU", 47.440, 19.260, 1, ["BUD"]),
    "IST": ("Istanbul", "TR", 41.275, 28.752, 3, ["IST", "SAW"]),
    "DXB": ("Dubaï", "AE", 25.250, 55.360, 4, ["DXB"]),
    "DOH": ("Doha", "QA", 25.270, 51.610, 3, ["DOH"]),
}
# Origine et hub identiques (même ville) : pas de montage Londres -> Londres
SAME_CITY = {"LHR": "LON", "FCO": "ROM"}


def coords(code: str):
    if code in ORIGINS:
        return ORIGINS[code][1], ORIGINS[code][2]
    if code in HUBS:
        return HUBS[code][2], HUBS[code][3]
    if code in DESTINATIONS:
        return DESTINATIONS[code][2], DESTINATIONS[code][3]
    return None


def airports_of(code: str) -> list:
    if code in HUBS:
        return HUBS[code][5]
    if code in DESTINATIONS:
        return DESTINATIONS[code][4] or [code]
    return [code]
