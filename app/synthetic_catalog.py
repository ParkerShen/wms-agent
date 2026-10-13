"""Deterministic, explicitly fictional warehouse and product catalogs."""

from typing import NamedTuple


class WarehouseSeed(NamedTuple):
    region: str
    region_cn: str
    country: str
    country_cn: str
    city: str
    city_cn: str
    code: str
    latitude: float
    longitude: float


WAREHOUSES = (
    WarehouseSeed("North America", "北美", "US", "美国", "Los Angeles", "洛杉矶", "USLAX", 33.9416, -118.4085),
    WarehouseSeed("North America", "北美", "US", "美国", "Dallas", "达拉斯", "USDFW", 32.8998, -97.0403),
    WarehouseSeed("North America", "北美", "US", "美国", "Chicago", "芝加哥", "USCHI", 41.8781, -87.6298),
    WarehouseSeed("North America", "北美", "US", "美国", "Atlanta", "亚特兰大", "USATL", 33.6407, -84.4277),
    WarehouseSeed("North America", "北美", "US", "美国", "Seattle", "西雅图", "USSEA", 47.4502, -122.3088),
    WarehouseSeed("North America", "北美", "US", "美国", "Miami", "迈阿密", "USMIA", 25.7617, -80.1918),
    WarehouseSeed("North America", "北美", "CA", "加拿大", "Toronto", "多伦多", "CATOR", 43.6532, -79.3832),
    WarehouseSeed("North America", "北美", "CA", "加拿大", "Vancouver", "温哥华", "CAVAN", 49.2827, -123.1207),
    WarehouseSeed("North America", "北美", "MX", "墨西哥", "Mexico City", "墨西哥城", "MXMEX", 19.4326, -99.1332),
    WarehouseSeed("North America", "北美", "MX", "墨西哥", "Monterrey", "蒙特雷", "MXMTY", 25.6866, -100.3161),
    WarehouseSeed("Europe", "欧洲", "GB", "英国", "London", "伦敦", "GBLON", 51.5072, -0.1276),
    WarehouseSeed("Europe", "欧洲", "GB", "英国", "Birmingham", "伯明翰", "GBBHM", 52.4862, -1.8904),
    WarehouseSeed("Europe", "欧洲", "DE", "德国", "Frankfurt", "法兰克福", "DEFRA", 50.1109, 8.6821),
    WarehouseSeed("Europe", "欧洲", "DE", "德国", "Hamburg", "汉堡", "DEHAM", 53.5488, 9.9872),
    WarehouseSeed("Europe", "欧洲", "FR", "法国", "Paris", "巴黎", "FRPAR", 48.8566, 2.3522),
    WarehouseSeed("Europe", "欧洲", "FR", "法国", "Lyon", "里昂", "FRLYS", 45.7640, 4.8357),
    WarehouseSeed("Europe", "欧洲", "NL", "荷兰", "Amsterdam", "阿姆斯特丹", "NLAMS", 52.3676, 4.9041),
    WarehouseSeed("Europe", "欧洲", "NL", "荷兰", "Rotterdam", "鹿特丹", "NLRTM", 51.9244, 4.4777),
    WarehouseSeed("Europe", "欧洲", "PL", "波兰", "Warsaw", "华沙", "PLWAW", 52.2297, 21.0122),
    WarehouseSeed("Europe", "欧洲", "ES", "西班牙", "Madrid", "马德里", "ESMAD", 40.4168, -3.7038),
    WarehouseSeed("Europe", "欧洲", "ES", "西班牙", "Barcelona", "巴塞罗那", "ESBCN", 41.3874, 2.1686),
    WarehouseSeed("Europe", "欧洲", "SE", "瑞典", "Stockholm", "斯德哥尔摩", "SESTO", 59.3293, 18.0686),
    WarehouseSeed("Europe", "欧洲", "IT", "意大利", "Milan", "米兰", "ITMIL", 45.4642, 9.1900),
    WarehouseSeed("Asia Pacific", "亚太", "AU", "澳大利亚", "Sydney", "悉尼", "AUSYD", -33.8688, 151.2093),
    WarehouseSeed("Asia Pacific", "亚太", "AU", "澳大利亚", "Melbourne", "墨尔本", "AUMEL", -37.8136, 144.9631),
    WarehouseSeed("Asia Pacific", "亚太", "AU", "澳大利亚", "Brisbane", "布里斯班", "AUBNE", -27.4698, 153.0251),
    WarehouseSeed("Asia Pacific", "亚太", "JP", "日本", "Tokyo", "东京", "JPTYO", 35.6762, 139.6503),
    WarehouseSeed("Asia Pacific", "亚太", "JP", "日本", "Osaka", "大阪", "JPOSA", 34.6937, 135.5023),
    WarehouseSeed("Asia Pacific", "亚太", "KR", "韩国", "Seoul", "首尔", "KRICN", 37.5665, 126.9780),
    WarehouseSeed("Asia Pacific", "亚太", "KR", "韩国", "Busan", "釜山", "KRPUS", 35.1796, 129.0756),
    WarehouseSeed("Asia Pacific", "亚太", "SG", "新加坡", "Singapore", "新加坡", "SGSIN", 1.3521, 103.8198),
    WarehouseSeed("Asia Pacific", "亚太", "CN", "中国", "Shanghai", "上海", "CNSHA", 31.2304, 121.4737),
    WarehouseSeed("Asia Pacific", "亚太", "CN", "中国", "Shenzhen", "深圳", "CNSZX", 22.5431, 114.0579),
    WarehouseSeed("Asia Pacific", "亚太", "IN", "印度", "Mumbai", "孟买", "INBOM", 19.0760, 72.8777),
    WarehouseSeed("Asia Pacific", "亚太", "IN", "印度", "Delhi", "德里", "INDEL", 28.6139, 77.2090),
    WarehouseSeed("Asia Pacific", "亚太", "TH", "泰国", "Bangkok", "曼谷", "THBKK", 13.7563, 100.5018),
    WarehouseSeed("Asia Pacific", "亚太", "VN", "越南", "Ho Chi Minh City", "胡志明市", "VNSGN", 10.8231, 106.6297),
    WarehouseSeed("Asia Pacific", "亚太", "MY", "马来西亚", "Kuala Lumpur", "吉隆坡", "MYKUL", 3.1390, 101.6869),
    WarehouseSeed("Asia Pacific", "亚太", "ID", "印度尼西亚", "Jakarta", "雅加达", "IDJKT", -6.2088, 106.8456),
    WarehouseSeed("Middle East & Africa", "中东和非洲", "AE", "阿联酋", "Dubai", "迪拜", "AEDXB", 25.2048, 55.2708),
    WarehouseSeed("Middle East & Africa", "中东和非洲", "SA", "沙特阿拉伯", "Riyadh", "利雅得", "SARUH", 24.7136, 46.6753),
    WarehouseSeed("Middle East & Africa", "中东和非洲", "TR", "土耳其", "Istanbul", "伊斯坦布尔", "TRIST", 41.0082, 28.9784),
    WarehouseSeed("Middle East & Africa", "中东和非洲", "ZA", "南非", "Johannesburg", "约翰内斯堡", "ZAJNB", -26.2041, 28.0473),
    WarehouseSeed("Middle East & Africa", "中东和非洲", "ZA", "南非", "Cape Town", "开普敦", "ZACPT", -33.9249, 18.4241),
    WarehouseSeed("Middle East & Africa", "中东和非洲", "KE", "肯尼亚", "Nairobi", "内罗毕", "KENBO", -1.2921, 36.8219),
    WarehouseSeed("Latin America", "拉丁美洲", "BR", "巴西", "Sao Paulo", "圣保罗", "BRSAO", -23.5505, -46.6333),
    WarehouseSeed("Latin America", "拉丁美洲", "BR", "巴西", "Rio de Janeiro", "里约热内卢", "BRRIO", -22.9068, -43.1729),
    WarehouseSeed("Latin America", "拉丁美洲", "CL", "智利", "Santiago", "圣地亚哥", "CLSCL", -33.4489, -70.6693),
    WarehouseSeed("Latin America", "拉丁美洲", "AR", "阿根廷", "Buenos Aires", "布宜诺斯艾利斯", "ARBUE", -34.6037, -58.3816),
    WarehouseSeed("Latin America", "拉丁美洲", "CO", "哥伦比亚", "Bogota", "波哥大", "COBOG", 4.7110, -74.0721),
)


# category code, category names, product names, material EN/CN, hazmat class, UN number, oversized
PRODUCT_FAMILIES = (
    ("HOME_STORAGE", "家居收纳", "Home Storage", "Stackable storage tote", "可叠放收纳箱", "polypropylene", "聚丙烯", None, None, False),
    ("HOME_STORAGE", "家居收纳", "Home Storage", "Under-bed organizer", "床底收纳盒", "woven polyester", "涤纶织物", None, None, False),
    ("KITCHEN", "厨房用品", "Kitchenware", "Stainless steel food container", "不锈钢保鲜盒", "stainless steel", "不锈钢", None, None, False),
    ("KITCHEN", "厨房用品", "Kitchenware", "Borosilicate glass baking dish", "高硼硅玻璃烤盘", "borosilicate glass", "高硼硅玻璃", None, None, False),
    ("SMALL_APPLIANCE", "小家电", "Small Appliances", "Compact air purifier", "桌面空气净化器", "ABS polymer", "ABS塑料", None, None, False),
    ("SMALL_APPLIANCE", "小家电", "Small Appliances", "Cordless hand blender", "无线手持搅拌机", "stainless steel", "不锈钢", None, None, False),
    ("ELECTRONICS", "消费电子", "Consumer Electronics", "Bluetooth noise-isolating headset", "蓝牙降噪耳机", "aluminum alloy", "铝合金", None, None, False),
    ("ELECTRONICS", "消费电子", "Consumer Electronics", "Portable USB-C monitor", "便携式USB-C显示器", "aluminum alloy", "铝合金", None, None, False),
    ("COMPUTER", "电脑及配件", "Computers & Accessories", "Mechanical keyboard", "机械键盘", "PBT polymer", "PBT塑料", None, None, False),
    ("COMPUTER", "电脑及配件", "Computers & Accessories", "Dual-band Wi-Fi router", "双频无线路由器", "ABS polymer", "ABS塑料", None, None, False),
    ("MOBILE_ACCESSORY", "移动设备配件", "Mobile Accessories", "Protective phone case", "防护手机壳", "thermoplastic polyurethane", "热塑性聚氨酯", None, None, False),
    ("OFFICE", "办公用品", "Office Supplies", "Archival document box", "档案收纳盒", "recycled board", "再生纸板", None, None, False),
    ("TOYS", "玩具", "Toys", "Magnetic construction set", "磁力拼搭套装", "ABS polymer", "ABS塑料", None, None, False),
    ("SPORTS", "运动用品", "Sports Equipment", "Adjustable resistance band set", "可调阻力带套装", "natural latex", "天然乳胶", None, None, False),
    ("OUTDOOR", "户外用品", "Outdoor Equipment", "Four-season camping sleeping bag", "四季露营睡袋", "ripstop polyester", "防撕裂涤纶", None, None, False),
    ("AUTOMOTIVE", "汽车用品", "Automotive Accessories", "All-weather cargo liner", "全天候后备箱垫", "thermoplastic elastomer", "热塑性弹性体", None, None, False),
    ("APPAREL", "服装", "Apparel", "Merino-blend hiking jacket", "美利奴混纺徒步夹克", "merino blend", "美利奴混纺", None, None, False),
    ("FOOTWEAR", "鞋类", "Footwear", "Trail running shoe", "越野跑鞋", "engineered mesh", "工程网布", None, None, False),
    ("BEAUTY", "美容工具", "Beauty Tools", "Rechargeable facial cleansing brush", "充电式洁面仪", "silicone", "硅胶", None, None, False),
    ("PERSONAL_CARE", "个人护理", "Personal Care", "Ceramic ionic hair dryer", "陶瓷负离子吹风机", "polycarbonate", "聚碳酸酯", None, None, False),
    ("PET", "宠物用品", "Pet Supplies", "Foldable fabric pet carrier", "折叠式宠物外出包", "600D polyester", "600D涤纶", None, None, False),
    ("FURNITURE", "家具", "Furniture", "Flat-pack writing desk", "平板包装书桌", "engineered wood", "工程木", None, None, True),
    ("FURNITURE", "家具", "Furniture", "Modular bookshelf", "模块化书架", "powder-coated steel", "喷粉钢材", None, None, True),
    ("LIGHTING", "照明", "Lighting", "Adjustable arc floor lamp", "可调弧形落地灯", "steel and aluminum", "钢铝材", None, None, True),
    ("SPORTS", "运动用品", "Sports Equipment", "Indoor cycle trainer", "室内骑行训练器", "steel frame", "钢制框架", None, None, True),
    ("OUTDOOR", "户外用品", "Outdoor Equipment", "Telescopic aluminum ladder", "伸缩铝合金梯", "aluminum alloy", "铝合金", None, None, True),
    ("BABY", "母婴用品", "Baby Products", "Convertible high chair", "可转换式儿童餐椅", "beech and polypropylene", "榉木和聚丙烯", None, None, True),
    ("HOME_TEXTILE", "家纺", "Home Textiles", "King-size quilted mattress topper", "特大号绗缝床垫保护层", "cotton blend", "棉混纺", None, None, True),
    ("INDUSTRIAL", "工业工具", "Industrial Tools", "Rolling steel tool cabinet", "带轮钢制工具柜", "powder-coated steel", "喷粉钢材", None, None, True),
    ("BUILDING", "建材五金", "Building & Hardware", "Acoustic wall panel kit", "吸音墙板套装", "PET felt", "PET纤维毡", None, None, True),
    ("PACKAGING", "包装耗材", "Packaging Supplies", "Reusable folding bulk crate", "可重复使用折叠周转箱", "high-density polyethylene", "高密度聚乙烯", None, None, True),
    ("BATTERY", "电池及储能", "Batteries & Energy Storage", "Lithium-ion power bank", "锂离子移动电源", "lithium-ion cells", "锂离子电芯", "Class 9", "UN3480", False),
    ("BATTERY", "电池及储能", "Batteries & Energy Storage", "Replacement lithium-ion tool battery", "电动工具替换锂电池", "lithium-ion cells", "锂离子电芯", "Class 9", "UN3480", False),
    ("BATTERY", "电池及储能", "Batteries & Energy Storage", "Rechargeable lantern with battery", "含电池可充电营地灯", "lithium-ion cells", "锂离子电芯", "Class 9", "UN3481", False),
    ("HAZMAT_AEROSOL", "气雾剂", "Aerosols", "Electronics contact-cleaner aerosol", "电子触点清洁气雾剂", "pressurized contents", "加压内容物", "Class 2.1", "UN1950", False),
    ("HAZMAT_FLAMMABLE", "易燃液体", "Flammable Liquids", "Citrus fragrance mist", "柑橘香氛喷雾", "alcohol-based liquid", "含醇液体", "Class 3", "UN1266", False),
    ("HAZMAT_FLAMMABLE", "易燃液体", "Flammable Liquids", "Water-based hobby paint set", "水性模型涂料套装", "coating material", "涂料类物质", "Class 3", "UN1263", False),
    ("HAZMAT_CORROSIVE", "腐蚀性物品", "Corrosives", "Workshop alkaline cleaner", "车间碱性清洁剂", "corrosive liquid", "腐蚀性液体", "Class 8", "UN1760", False),
    ("HAZMAT_FLAMMABLE", "易燃液体", "Flammable Liquids", "Adhesive remover solvent", "除胶溶剂", "flammable liquid", "易燃液体", "Class 3", "UN1993", False),
    ("INDUSTRIAL", "工业工具", "Industrial Tools", "Cordless impact wrench kit", "无线冲击扳手套装", "lithium-ion battery included", "含锂离子电池", "Class 9", "UN3481", False),
)

COLORS = (
    ("graphite", "石墨灰", "graphite gray"),
    ("navy", "海军蓝", "navy blue"),
    ("ivory", "象牙白", "ivory"),
    ("forest", "森林绿", "forest green"),
    ("sand", "沙色", "sand"),
    ("black", "曜石黑", "onyx black"),
    ("silver", "银色", "silver"),
    ("terracotta", "陶土红", "terracotta"),
    ("sage", "鼠尾草绿", "sage green"),
    ("cobalt", "钴蓝", "cobalt blue"),
)

MATERIALS = (
    ("standard", "标准款", "standard"),
    ("compact", "紧凑款", "compact"),
    ("reinforced", "加强款", "reinforced"),
    ("lightweight", "轻量款", "lightweight"),
    ("premium", "优选款", "premium"),
)
