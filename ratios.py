def calculate_roic(stock):
    try:
        fin = stock.financials
        bs = stock.balance_sheet
        
        # 1. Obtención de EBIT (Ganancia Operativa)
        ebit = fin.loc['EBIT'].iloc[0] if 'EBIT' in fin.index else (
            fin.loc['Operating Income'].iloc[0] if 'Operating Income' in fin.index else 0
        )
        
        # 2. Cálculo de la Tasa Efectiva de Impuestos para determinar el NOPAT
        tax_provision = fin.loc['Tax Provision'].iloc[0] if 'Tax Provision' in fin.index else 0
        pretax_income = fin.loc['Pretax Income'].iloc[0] if 'Pretax Income' in fin.index else 0
        
        if pretax_income > 0 and tax_provision > 0:
            effective_tax_rate = tax_provision / pretax_income
        else:
            effective_tax_rate = 0.21  # Tasa corporativa estándar (21%) de respaldo
            
        nopat = ebit * (1 - effective_tax_rate)
        
        # 3. Cálculo de Capital Invertido (Deuda Total + Capital - Efectivo Excedente)
        total_debt = bs.loc['Total Debt'].iloc[0] if 'Total Debt' in bs.index else 0
        equity = bs.loc['Stockholders Equity'].iloc[0] if 'Stockholders Equity' in bs.index else 0
        cash = bs.loc['Cash And Cash Equivalents'].iloc[0] if 'Cash And Cash Equivalents' in bs.index else 0
        
        invested_capital = (total_debt + equity) - cash
        
        # 4. ROIC = NOPAT / Capital Invertido
        return round((nopat / invested_capital) * 100, 2) if invested_capital > 0 else 0

    except Exception:
        return 0

def calculate_roa(stock):
    try:
        fin = stock.financials
        bs = stock.balance_sheet
        
        # 1. Obtención de Ingresos Netos
        net_income = fin.loc['Net Income'].iloc[0] if 'Net Income' in fin.index else 0
        
        # 2. Cálculo de Activos Totales
        total_assets = bs.loc['Total Assets'].iloc[0] if 'Total Assets' in bs.index else 0
        
        # 3. ROA = Ingresos Netos / Activos Totales
        return round((net_income / total_assets) * 100, 2) if total_assets > 0 else 0

    except Exception:
        return 0

def calculate_roe(stock):
    try:
        fin = stock.financials
        bs = stock.balance_sheet
        
        # 1. Obtención de Ingresos Netos
        net_income = fin.loc['Net Income'].iloc[0] if 'Net Income' in fin.index else 0
        
        # 2. Cálculo de Patrimonio Neto
        equity = bs.loc['Stockholders Equity'].iloc[0] if 'Stockholders Equity' in bs.index else 0
        
        # 3. ROE = Ingresos Netos / Patrimonio Neto
        return round((net_income / equity) * 100, 2) if equity > 0 else 0

    except Exception:
        return 0

def calculate_liquidity_ratio(stock):
    try:
        bs = stock.balance_sheet
        
        # 1. Cálculo de Activos Corrientes y Pasivos Corrientes
        current_assets = bs.loc['Current Assets'].iloc[0] if 'Current Assets' in bs.index else 0
        current_liabilities = bs.loc['Current Liabilities'].iloc[0] if 'Current Liabilities' in bs.index else 0
        
        # 2. Liquidity Ratio = Activos Corrientes / Pasivos Corrientes
        return round(current_assets / current_liabilities, 2) if current_liabilities > 0 else 0

    except Exception:
        return 0

def calculate_immediate_liquidity_ratio(stock):
    try:
        bs = stock.balance_sheet
        
        # 1. Cálculo de Activos Líquidos y Pasivos Corrientes
        current_assets = bs.loc['Current Assets'].iloc[0] if 'Current Assets' in bs.index else 0
        current_liabilities = bs.loc['Current Liabilities'].iloc[0] if 'Current Liabilities' in bs.index else 0
        inventory = bs.loc['Inventory'].iloc[0] if 'Inventory' in bs.index else 0
        
        # 2. Immediate Liquidity Ratio = Activos Líquidos / Pasivos Corrientes
        return round((current_assets - inventory) / current_liabilities, 2) if current_liabilities > 0 else 0

    except Exception:
        return 0

def calculate_average_payment_period(stock):
    try:
        fin = stock.financials
        bs = stock.balance_sheet
        
        # 1. Cálculo de Cuentas por Pagar y Costo de Ventas
        accounts_payable = bs.loc['Accounts Payable'].iloc[0] if 'Accounts Payable' in bs.index else 0
        cost_of_goods_sold = fin.loc['Cost Of Revenue'].iloc[0] if 'Cost Of Revenue' in fin.index else 0
        
        # 2. Average Payment Period = (Cuentas por Pagar / Costo de Ventas) * 360
        return round((accounts_payable / cost_of_goods_sold) * 360, 2) if cost_of_goods_sold > 0 else 0

    except Exception:
        return 0

def calculate_average_collection_period(stock):
    try:
        fin = stock.income_stmt
        bs = stock.balance_sheet
        
        # 1. Cálculo de Cuentas por Cobrar y Ventas Netas
        accounts_receivable = bs.loc['Accounts Receivable'].iloc[0]
        net_sales = fin.loc['Net Income'].iloc[0]
        
        # 2. Average Collection Period = (Cuentas por Cobrar / Ventas Netas) * 360
        return round((accounts_receivable / net_sales) * 360, 2) if net_sales > 0 else 0

    except Exception:
        return 0

def calculate_inventory_days(stock):
    try:
        fin = stock.financials
        bs = stock.balance_sheet
        
        # 1. Cálculo de Inventario y Costo de Ventas
        media_inventory = bs.loc['Inventory'].iloc[0] if 'Inventory' in bs.index else 0
        cost_of_goods_sold = fin.loc['Cost Of Revenue'].iloc[0] if 'Cost Of Revenue' in fin.index else 0
        
        # 2. Inventory Days = (Inventario / Costo de Ventas) * 360
        return round((media_inventory / cost_of_goods_sold) * 360, 2) if cost_of_goods_sold > 0 else 0

    except Exception:
        return 0

def calculate_net_margin(stock):
    try:
        fin = stock.financials
        
        # 1. Cálculo de Ingresos Netos y Ventas Netas
        net_income = fin.loc['Net Income'].iloc[0] if 'Net Income' in fin.index else 0
        net_sales = fin.loc['Total Revenue'].iloc[0] if 'Total Revenue' in fin.index else 0
        
        # 2. Net Margin = Ingresos Netos / Ventas Netas
        return round((net_income / net_sales) * 100, 2) if net_sales > 0 else 0

    except Exception:
        return 0

def calculate_debt_to_equity_ratio(stock):
    try:
        bs = stock.balance_sheet
        
        # 1. Cálculo de Deuda Total y Patrimonio Neto
        total_liabilities = bs.loc['Total Liabilities Net Minority Interest'].iloc[0] if 'Total Liabilities Net Minority Interest' in bs.index else 0
        equity = bs.loc['Stockholders Equity'].iloc[0] if 'Stockholders Equity' in bs.index else 0
        
        # 2. Debt to Equity Ratio = Deuda Total / Patrimonio Neto
        return round((total_liabilities / equity), 2) if equity > 0 else 0

    except Exception:
        return 0

def calculate_interest_coverage(stock):
    try:
        fin = stock.financials
        
        # 1. Cálculo de EBIT (Ganancia Operativa)
        ebit = fin.loc['EBIT'].iloc[0] if 'EBIT' in fin.index else (
            fin.loc['Operating Income'].iloc[0] if 'Operating Income' in fin.index else 0
        )
        
        # 2. Cálculo de Gastos por Intereses
        interest_expense = fin.loc['Interest Expense'].iloc[0] if 'Interest Expense' in fin.index else 0
        
        # 3. Interest Coverage Ratio = EBIT / Gastos por Intereses
        return round((ebit / interest_expense), 2) if interest_expense > 0 else None

    except Exception:
        return None



