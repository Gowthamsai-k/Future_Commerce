from commerce.db.connection import get_connection

PRODUCTS = [
    # Gaming Mice
    ("Logitech G102 Gaming Mouse", 1299, "Lightweight wired gaming mouse with 8000 DPI sensor and RGB lighting", "mouse", "Logitech", 25),
    ("Razer DeathAdder Essential", 1999, "Ergonomic wired gaming mouse with 6400 DPI optical sensor", "mouse", "Razer", 20),
    ("Razer Viper Mini Ultra-Lightweight", 2499, "61g ultra-lightweight gaming mouse with Speedflex cable and Chroma RGB", "mouse", "Razer", 18),
    ("Logitech G305 Lightspeed Wireless Mouse", 2999, "Next-gen HERO sensor with 12000 DPI and 250h battery life", "mouse", "Logitech", 15),
    ("SteelSeries Rival 3 RGB", 2199, "TrueMove Core optical gaming sensor with prism RGB lighting", "mouse", "SteelSeries", 12),

    # Mechanical Keyboards
    ("Cosmic Byte CB-GK-16 Firefly TKL Keyboard", 2199, "Tenkeyless mechanical RGB gaming keyboard with Outemu Blue switches", "keyboard", "Cosmic Byte", 30),
    ("Redragon K552 Mechanical Keyboard", 2499, "Compact 87-key mechanical RGB gaming keyboard with dustproof switches", "keyboard", "Redragon", 20),
    ("Corsair K55 RGB PRO Gaming Keyboard", 3799, "Dynamic 5-zone RGB backlighting with 6 dedicated macro keys", "keyboard", "Corsair", 14),
    ("Razer BlackWidow V3 Tenkeyless", 6999, "Compact mechanical keyboard with Razer Green tactile switches", "keyboard", "Razer", 10),
    ("Keychron K2 Wireless Mechanical Keyboard", 7499, "75% layout wireless Bluetooth mechanical keyboard for PC and Mac", "keyboard", "Keychron", 8),

    # Gaming Headsets
    ("Cosmic Byte GS430 Gaming Headset", 899, "Over-ear gaming headset with 3D surround sound and flexible mic", "headset", "Cosmic Byte", 35),
    ("HyperX Cloud Stinger 2", 3499, "Lightweight gaming headset with 50mm directional drivers and swivel mic", "headset", "HyperX", 18),
    ("Razer BlackShark V2 X", 4299, "50mm TriForce drivers with HyperClear cardioid mic and 7.1 surround sound", "headset", "Razer", 16),
    ("Logitech G435 Wireless Headset", 4999, "Ultra-lightweight wireless Bluetooth gaming headset with dual beamforming mics", "headset", "Logitech", 12),
    ("SteelSeries Arctis Nova 1", 5499, "Nova Acoustic System with Custom-tuned High Fidelity Drivers", "headset", "SteelSeries", 10),

    # Controllers
    ("Redragon G808 Harrow Wireless Gamepad", 1599, "2.4GHz wireless PC gamepad with dual vibration feedback motors", "controller", "Redragon", 25),
    ("Cosmic Byte Ares Wireless Gaming Controller", 1999, "Wireless gamepad with magnetic trigger buttons and textured grips", "controller", "Cosmic Byte", 22),
    ("Xbox Wireless Controller (Carbon Black)", 5499, "Official Xbox wireless controller with textured grip and hybrid D-pad", "controller", "Microsoft", 15),
    ("DualSense Wireless Controller for PS5", 5999, "Haptic feedback and adaptive triggers for immersive gaming", "controller", "Sony", 12),

    # Gaming Monitors
    ("Acer Nitro 24 Inch FHD 165Hz Gaming Monitor", 11999, "23.8 inch Full HD IPS panel with 165Hz refresh rate and 0.5ms response time", "monitor", "Acer", 10),
    ("LG Ultragear 24 Inch FHD 144Hz IPS Monitor", 13499, "1ms MBR, AMD FreeSync Premium, 99% sRGB color accuracy gaming display", "monitor", "LG", 9),
    ("Samsung Odyssey G3 27 Inch 144Hz Monitor", 16999, "27 inch Full HD VA panel with 144Hz, 1ms response and height adjustable stand", "monitor", "Samsung", 8),
    ("ASUS TUF Gaming 27 Inch WQHD 170Hz Monitor", 24999, "27 inch 1440p QHD Fast IPS panel with 170Hz refresh rate and Extreme Low Motion Blur", "monitor", "ASUS", 5),

    # Gaming Laptops
    ("Lenovo IdeaPad Gaming 3", 46999, "AMD Ryzen 5 5500H, GTX 1650 4GB, 8GB RAM, 512GB SSD, 120Hz Display", "laptop", "Lenovo", 6),
    ("ASUS TUF Gaming F15", 54999, "Intel Core i5 11th Gen, RTX 3050 4GB, 16GB RAM, 512GB SSD, 144Hz FHD", "laptop", "ASUS", 7),
    ("Acer Nitro V15", 72999, "Intel Core i5 13th Gen, RTX 4050 6GB, 16GB RAM, 512GB SSD, 144Hz Display", "laptop", "Acer", 5),
    ("HP Victus Gaming Laptop", 88999, "AMD Ryzen 7 7840HS, RTX 4060 8GB, 16GB RAM, 1TB SSD, 144Hz Display", "laptop", "HP", 4),

    # Accessories & Gaming Chairs
    ("Redragon P002 Extended Gaming Mouse Pad", 499, "Waterproof anti-slip rubber base stitched edge mouse pad", "mousepad", "Redragon", 40),
    ("Cosmic Byte Extended RGB Mouse Pad", 699, "Large 800x300mm gaming mouse pad with 14 RGB lighting modes", "mousepad", "Cosmic Byte", 30),
    ("Green Soul Beast Racing Ergonomic Gaming Chair", 14999, "High back gaming chair with neck cushion and lumbar pillow support", "chair", "Green Soul", 6),
    ("Elgato Stream Deck MK.2", 13999, "15 customizable LCD keys for stream controls, hotkeys and soundboard", "accessory", "Corsair", 4),
]


def seed_products() -> None:
    connection = get_connection()
    connection.execute("BEGIN IMMEDIATE")
    for name, price, description, category, brand, stock in PRODUCTS:
        existing = connection.execute("SELECT id FROM products WHERE name = ?", (name,)).fetchone()
        if existing:
            connection.execute("""
                UPDATE products SET price = ?, description = ?, category = ?, brand = ?, stock = ? WHERE id = ?
            """, (price, description, category, brand, stock, existing["id"]))
        else:
            connection.execute("""
                INSERT INTO products (name, price, description, category, brand, stock)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (name, price, description, category, brand, stock))
    connection.commit()
    connection.close()