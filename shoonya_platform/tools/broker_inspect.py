from shoonya_platform.brokers.shoonya.client import ShoonyaClient
from shoonya_platform.utils.utils import safe_api_call

import pandas as pd
from tabulate import tabulate
from shoonya_platform.logging.logger_config import get_component_logger
from typing import Optional

logger = get_component_logger('execution_service')


# Function to fetch and display limits
def limit(api_client: ShoonyaClient):
    try:
        # Fetch limits from the API
        limits = safe_api_call(api_client.get_limits)

        # Convert the dictionary to a DataFrame
        df = pd.DataFrame([limits])

        # Display the table using tabulate
        print(tabulate(df, headers='keys', tablefmt='pretty', showindex=False))
        return df

    except Exception as e:
        print(f"Error fetching limits: {e}")

# Function to fetch and display positions
def position(api_client: ShoonyaClient):
    try:
        # Fetch positions from the API
        positions = safe_api_call(api_client.get_positions)

        # Check if positions are available
        if not positions:
            print("No positions found.")
            return

        # Convert positions to a DataFrame
        df = pd.DataFrame(positions)

        # Select only the required columns
        df = df[['token', 's_prdt_ali', 'tsym', 'lp', 'rpnl', 'urmtom', 'netqty', 'totbuyavgprc', 'totsellavgprc']]

        # Convert numeric columns to appropriate types
        df['lp'] = df['lp'].astype(float)
        df['rpnl'] = df['rpnl'].astype(float)
        df['urmtom'] = df['urmtom'].astype(float)
        df['netqty'] = df['netqty'].astype(int)
        df['totbuyavgprc'] = df['totbuyavgprc'].astype(float)
        df['totsellavgprc'] = df['totsellavgprc'].astype(float)

        # Display the table using tabulate
        print(tabulate(df, headers='keys', tablefmt='pretty', showindex=False))
        return df

    except Exception as e:
        print(f"Error fetching positions: {e}")

# Function to fetch and display holdings
def holding(api_client: ShoonyaClient):
    try:
        # Fetch holdings from the API
        holdings = safe_api_call(api_client.get_holdings)

        # Check if holdings are available
        if not holdings:
            print("No holdings found.")
            return

        # Flatten the nested dictionaries in 'exch_tsym' column
        flattened_holdings = []
        for holding in holdings:
            for exch_tsym in holding['exch_tsym']:
                flattened_holding = {
                    'exch': exch_tsym['exch'],
                    'token': exch_tsym['token'],
                    'tsym': exch_tsym['tsym'],
                    'holdqty': holding['holdqty'],
                    'upldprc': holding['upldprc'],
                    'colqty': holding['colqty'],
                    'unplgdqty': holding['unplgdqty'],
                    'btstqty': holding['btstqty']
                }
                flattened_holdings.append(flattened_holding)

        # Convert flattened holdings to a DataFrame
        df = pd.DataFrame(flattened_holdings)

        # Group by 'tsym' and aggregate the data
        df = df.groupby('tsym').agg({
            'exch': 'first',
            'token': 'first',
            'holdqty': 'sum',
            'upldprc': 'first',
            'colqty': 'sum',
            'unplgdqty': 'sum',
            'btstqty': 'sum'
        }).reset_index()

        # Display the table using tabulate
        print(tabulate(df, headers='keys', tablefmt='pretty', showindex=False))
        return df

    except Exception as e:
        print(f"Error fetching holdings: {e}")

# Function to fetch and display order book
def orderbook(api_client: ShoonyaClient):
    try:
        # Fetch order book from the API
        orders = safe_api_call(api_client.get_order_book)

        # Check if orders are available
        if not orders:
            print("No orders found.")
            return

        # Convert orders to a DataFrame
        df = pd.DataFrame(orders)

        # Select only the required columns
        df = df[['norenordno', 'tsym', 'prd', 'status', 'qty', 'trantype', 'exch']]

        # Display the table using tabulate
        print(tabulate(df, headers='keys', tablefmt='pretty', showindex=False))
        return df

    except Exception as e:
        print(f"Error fetching order book: {e}")

# Function to fetch and display trade book
def tradebook(api_client: ShoonyaClient):
    try:
        # Fetch trade book from the API
        trades = safe_api_call(api_client.get_trade_book)

        # Check if trades are available
        if not trades:
            print("No trades found.")
            return

        # Convert trades to a DataFrame
        df = pd.DataFrame(trades)

        # Select only the required columns
        df = df[['norenordno', 'tsym', 'qty', 'fillshares', 'avgprc','flprc', 'trantype', 'exch']]

        # Display the table using tabulate
        print(tabulate(df, headers='keys', tablefmt='pretty', showindex=False))
        return df

    except Exception as e:
        print(f"Error fetching trade book: {e}")

# Function to fetch positions for specific symbols
def get_symbols_position(api_client: ShoonyaClient, symbols):
    try:
        # Fetch positions from the API
        positions = safe_api_call(api_client.get_positions)

        # Check if positions are available
        if not positions:
            print("No positions found.")
            return

        # Convert positions to a DataFrame
        df = pd.DataFrame(positions)

        # Select only the required columns
        df = df[['token', 's_prdt_ali', 'tsym', 'lp', 'rpnl', 'urmtom', 'netqty', 'totbuyavgprc', 'totsellavgprc']]

        # Convert numeric columns to appropriate types
        df[['lp', 'rpnl', 'urmtom', 'totbuyavgprc', 'totsellavgprc']] = df[['lp', 'rpnl', 'urmtom', 'totbuyavgprc', 'totsellavgprc']].astype(float)
        df['netqty'] = df['netqty'].astype(int)

        # Filter for the specified symbols
        symbol_df = df[df['tsym'].isin(symbols)]

        if symbol_df.empty:
            print(f"No positions found for symbols: {symbols}")
            return None

        # Display the table using tabulate
        print(tabulate(symbol_df, headers='keys', tablefmt='pretty', showindex=False))

        return symbol_df

    except Exception as e:
        print(f"Error fetching positions: {e}")
        return None

# Example usage
# get_symbols_position(["NIFTY30DEC25C26000", "NIFTY30DEC25P26000"])

def search_all(
    api_client: ShoonyaClient,
    symbol_name: str,
    exchange_filter: Optional[str] = None
) -> pd.DataFrame:
    """
    Search for a symbol across multiple exchanges.

    Retry logic is handled ONLY by safe_api_call.

    Args:
        api_client (ShoonyaClient): Logged-in Shoonya client
        symbol_name (str): Symbol to search
        exchange_filter (str, optional): Restrict search to one exchange

    Returns:
        pd.DataFrame: Matching symbols across exchanges
    """

    exchanges = ['NSE', 'NFO', 'BSE', 'BFO', 'MCX', 'CDS']
    results = []

    if exchange_filter:
        exchange_filter = exchange_filter.upper()
        if exchange_filter not in exchanges:
            logger.error("Invalid exchange filter: %s", exchange_filter)
            return pd.DataFrame()
        exchanges = [exchange_filter]

    for exch in exchanges:
        logger.info("Searching %s for symbol: %s", exch, symbol_name)

        response = safe_api_call(
            api_client.searchscrip,
            exchange=exch,
            searchtext=symbol_name
        )

        if not response:
            logger.warning("Search failed for %s (no response)", exch)
            continue

        if response.get("stat") != "Ok":
            logger.warning(
                "Search failed for %s: %s",
                exch,
                response.get("emsg", "Unknown error")
            )
            continue

        values = response.get("values", [])
        if not values:
            logger.info("No symbols found in %s", exch)
            continue

        for entry in values:
            results.append({
                "Exchange": exch,
                "Symbol": entry.get("tsym", ""),
                "Token": entry.get("token", ""),
                "Segment": entry.get("seg", ""),
                "Expiry": entry.get("exd", ""),
                "Lot Size": entry.get("ls", ""),
                "Instrument": entry.get("instname", "")
            })

    df = pd.DataFrame(results)

    if df.empty:
        logger.info(f"No results found for symbol {symbol_name}")
    else:
        logger.info(f"Found {len(df)} results for {symbol_name}")
        print(df)

    return df