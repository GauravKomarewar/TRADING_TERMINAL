from shoonya_platform.execution.intent import UniversalOrderCommand

def validate_order(cmd: UniversalOrderCommand) -> None:
    """
    Hard validation layer.
    Any failure here MUST reject the command.
    """

    # -----------------------
    # Basic sanity
    # -----------------------
    if cmd.quantity <= 0:
        raise ValueError("Quantity must be positive")

    if cmd.side not in ("BUY", "SELL"):
        raise ValueError("Invalid order side")

    # -----------------------
    # Order type rules
    # -----------------------
    if cmd.order_type in ("LIMIT", "SL") and cmd.price is None:
        raise ValueError(f"{cmd.order_type} order requires price")

    if cmd.order_type == "LEVEL":
        if cmd.trigger_type == "NONE":
            raise ValueError("LEVEL order requires trigger type")
        if cmd.trigger_price is None:
            raise ValueError("LEVEL order requires trigger price")

    # -----------------------
    # Trigger validation
    # -----------------------
    if cmd.trigger_type != "NONE":
        if cmd.trigger_price is None:
            raise ValueError("Trigger price missing")

        if cmd.trigger_execution == "LIMIT" and cmd.trigger_limit_price is None:
            raise ValueError("Trigger LIMIT requires trigger_limit_price")

    # -----------------------
    # Risk rules
    # -----------------------
    if cmd.target and not cmd.stop_loss:
        raise ValueError("Target requires stop loss")

    if cmd.stop_loss and cmd.price:
        if cmd.side == "BUY" and cmd.stop_loss >= cmd.price:
            raise ValueError("BUY stop loss must be below entry price")
        if cmd.side == "SELL" and cmd.stop_loss <= cmd.price:
            raise ValueError("SELL stop loss must be above entry price")

    # -----------------------
    # Trailing rules
    # -----------------------
    if cmd.trailing_type != "NONE":
        if cmd.stop_loss is None:
            raise ValueError("Trailing requires initial stop loss")
        if cmd.trailing_value is None:
            raise ValueError("Trailing value missing")

        if cmd.trailing_type == "POINTS" and cmd.trailing_value <= 0:
            raise ValueError("Trailing points must be positive")

        if cmd.trailing_type == "PERCENT":
            if not (0 < cmd.trailing_value < 100):
                raise ValueError("Trailing percent must be between 0 and 100")

    # -----------------------
    # Bracket / Cover
    # -----------------------
    if cmd.order_type in ("BRACKET", "COVER"):
        if cmd.stop_loss is None:
            raise ValueError(f"{cmd.order_type} order requires stop loss")

        if cmd.order_type == "BRACKET" and cmd.target is None:
            raise ValueError("BRACKET order requires target")
