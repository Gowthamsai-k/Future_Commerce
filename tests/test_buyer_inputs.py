from commerce.ai.buyer import build_follow_up_question, normalize_buyer_request


def test_normalize_buyer_request_keeps_only_query_values():
    request = normalize_buyer_request(
        product_request="List the available products under $200",
        budget=None,
        customer_name=None,
        customer_email=None,
        shipping_address=None,
        quantity=None,
        payment_method=None,
    )

    assert request["product_request"] == "List the available products under $200"
    assert request["budget"] is None
    assert request["customer_name"] is None
    assert request["customer_email"] is None
    assert request["shipping_address"] is None
    assert request["quantity"] == 1
    assert request["payment_method"] is None


def test_normalize_buyer_request_preserves_user_values():
    request = normalize_buyer_request(
        product_request="Order one PlayStation 5 controller",
        budget=120.0,
        customer_name="Ada",
        customer_email="ada@example.com",
        shipping_address="123 Main St",
        quantity=1,
        payment_method="card",
    )

    assert request["budget"] == 120.0
    assert request["customer_name"] == "Ada"
    assert request["customer_email"] == "ada@example.com"
    assert request["shipping_address"] == "123 Main St"
    assert request["quantity"] == 1
    assert request["payment_method"] == "card"


def test_normalize_buyer_request_rejects_invalid_numeric_values():
    try:
        normalize_buyer_request(product_request="Buy a headset", budget=0, quantity=0)
        assert False, "Expected ValueError for invalid purchase values"
    except ValueError:
        pass


def test_build_follow_up_question_for_budget_or_alternative():
    question = build_follow_up_question(
        requested_product="gaming mouse",
        alternative_product="Mechanical gaming keyboard",
        current_budget=120,
        alternative_price=150,
    )

    assert "budget" in question.lower()
    assert "alternative" in question.lower() or "switch" in question.lower()
    assert "120" in question
    assert "150" in question


def test_build_follow_up_question_for_missing_details():
    question = build_follow_up_question(
        requested_product="headset",
        current_budget=80,
        missing_fields={"customer_email": "email", "shipping_address": "delivery address"},
    )

    assert "email" in question.lower()
    assert "address" in question.lower()
