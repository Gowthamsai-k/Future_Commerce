from database import get_connection


def seed_products():

    conn = get_connection()

    count = conn.execute(
        "SELECT COUNT(*) FROM products"
    ).fetchone()[0]

    if count > 0:
        conn.close()
        return

    products = [

        (
            "Logitech G102 Gaming Mouse",
            1299,
            "Lightweight wired gaming mouse with adjustable DPI",
            "mouse",
            "Logitech",
            25
        ),

        (
            "Razer DeathAdder Essential",
            1999,
            "Ergonomic gaming mouse with 6400 DPI sensor",
            "mouse",
            "Razer",
            15
        ),

        (
            "Redragon K552 Mechanical Keyboard",
            2499,
            "Mechanical RGB gaming keyboard with blue switches",
            "keyboard",
            "Redragon",
            20
        ),

        (
            "HyperX Cloud Stinger 2",
            3499,
            "Gaming headset with comfortable ear cushions and clear microphone",
            "headset",
            "HyperX",
            12
        ),

        (
            "Logitech G435 Wireless Headset",
            4999,
            "Lightweight wireless gaming headset",
            "headset",
            "Logitech",
            8
        ),

        (
            "Xbox Wireless Controller",
            5499,
            "Wireless gaming controller compatible with Xbox and PC",
            "controller",
            "Microsoft",
            10
        ),

        (
            "Cosmic Byte Gaming Mouse Pad",
            699,
            "Large extended mouse pad for gaming setups",
            "mousepad",
            "Cosmic Byte",
            30
        ),

        (
            "Acer Nitro 24 Gaming Monitor",
            11999,
            "24 inch Full HD gaming monitor with high refresh rate",
            "monitor",
            "Acer",
            7
        )

    ]

    conn.executemany(
        """
        INSERT INTO products
        (
            name,
            price,
            description,
            category,
            brand,
            stock
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        products
    )

    conn.commit()
    conn.close()


seed_products()