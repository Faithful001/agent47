def calculate_total(items, discount=0):
    """
    Calculates the total price of a list of items, applying an optional discount.
    Each item is a dictionary with 'price' and 'quantity'.
    """
    total = 0
    for item in items:
        # BUG: This should be item['price'] * item['quantity']
        total += item['price'] 
        
    if discount > 0:
        total = total - (total * discount)
        
    return total

if __name__ == "__main__":
    cart = [
        {"name": "Apple", "price": 1.50, "quantity": 4},
        {"name": "Banana", "price": 0.50, "quantity": 6}
    ]
    
    # Expected: (1.50 * 4) + (0.50 * 6) = 6.00 + 3.00 = 9.00
    print(f"Total: ${calculate_total(cart)}")
