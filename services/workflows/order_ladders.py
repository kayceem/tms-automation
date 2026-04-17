"""Pure ladder and quantity calculation helpers for order workflows."""

import math
from typing import List, Optional, Tuple


def calculate_price_levels(
    base_price: float,
    limit_price: Optional[float] = None,
    no_ladder: bool = False,
) -> Tuple[List[float], List[int]]:
    """Calculate the standard IPO price ladder."""
    if no_ladder:
        return [base_price], [0]

    price_increments = [0, 3, 3, 3, 3, 3]
    price_levels: List[float] = []
    actual_increments: List[int] = []

    current_price = base_price
    for increment in price_increments:
        new_price = current_price * (1 + increment / 100)
        floored_price = math.floor(new_price * 10) / 10
        current_price = floored_price
        price_levels.append(floored_price)
        actual_increments.append(increment)

    if limit_price is not None:
        max_price_raw = limit_price * 1.15
        max_price = math.floor(max_price_raw * 10) / 10

        filtered_levels = []
        filtered_increments = []
        for price, increment in zip(price_levels, actual_increments):
            if price <= max_price:
                filtered_levels.append(price)
                filtered_increments.append(increment)

        if not filtered_levels or filtered_levels[-1] != max_price:
            filtered_levels.append(max_price)
            filtered_increments.append(15)

        price_levels = filtered_levels
        actual_increments = filtered_increments

    return price_levels, actual_increments


def calculate_lower_price_levels(
    base_price: float,
    limit_price: Optional[float] = None,
) -> Tuple[List[float], List[int]]:
    """Calculate the lower trigger ladder used by ipo-trigger-low mode."""
    if limit_price is not None and base_price < limit_price:
        reference_price = limit_price
        price_decrements = [8, 9]
    else:
        reference_price = base_price
        price_decrements = [9, 10]

    price_levels: List[float] = []
    for decrement in price_decrements:
        new_price = reference_price * (1 - decrement / 100)
        floored_price = math.floor(new_price * 10) / 10
        price_levels.append(floored_price)

    return price_levels, price_decrements


def get_quantity_for_level(
    level_num: int,
    total_levels: int,
    order_quantity: int,
    base_quantity: Optional[int],
) -> int:
    """Determine the quantity to use for a ladder level."""
    if level_num == total_levels:
        return order_quantity
    if base_quantity is not None:
        return base_quantity
    return order_quantity
