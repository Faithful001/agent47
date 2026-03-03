import pytest

def calculate_total(items, discount=0):
    total = 0
    for item in items:
        total += item['price'] * item['quantity']  
    if discount > 0:
        total = total - (total * discount)
    return total

def test_calculate_total_without_discount():
    cart = [
        {"name": "Apple", "price": 1.50, "quantity": 4},
        {"name": "Banana", "price": 0.50, "quantity": 6}
    ]
    assert calculate_total(cart) == 9.00

def test_calculate_total_with_discount():
    cart = [
        {"name": "Laptop", "price": 1000.00, "quantity": 1},
        {"name": "Mouse", "price": 25.00, "quantity": 2}
    ]
    # 1050 * 0.9 = 945
    assert calculate_total(cart, discount=0.10) == 945.00
