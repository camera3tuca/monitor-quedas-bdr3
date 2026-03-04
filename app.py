import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib.pyplot as plt
import seaborn as sns
import requests
from datetime import datetime
import pytz
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Monitor BDRs - Swing Trade",
    page_icon="📉",
    layout="wide"
)

warnings.filterwarnings('ignore')
plt.style.use('seaborn-v0_8-darkgrid')
sns.set_palette("husl")

PERIODO = "1y"  # 1 ano para ter dados suficientes para EMA200 (~252 dias úteis)
TERMINACOES_BDR = ('31', '32', '33', '34', '35', '39')

# API Key Massive para dados fundamentalistas
MASSIVE_API_KEY = "VIvP42Yjpz8vkGuCpvIT5Pz2lpdjVdj6"

# =============================================================================
# MAPEAMENTO BDR → TICKER US PARA DADOS FUNDAMENTALISTAS
# =============================================================================
TICKER_MAP = {
    # As 7 Magníficas
    'AMZO34': 'AMZN', 'GOGL34': 'GOOGL', 'GOGL35': 'GOOG', 'FBOK34': 'META',
    'MSFT34': 'MSFT', 'AAPL34': 'AAPL', 'NVDC34': 'NVDA', 'TSLA34': 'TSLA',
    'M1TA34': 'META',
    # Fintech/Pagamentos
    'ROXO34': 'NU', 'PAGS34': 'PAGS', 'STNE34': 'STNE', 'INBR32': 'INTR',
    'V1SA34': 'V', 'MSCD34': 'MA', 'PYPL34': 'PYPL',
    # Outros populares
    'DISB34': 'DIS', 'NFLX34': 'NFLX', 'MELI34': 'MELI', 'BERK34': 'BRK-B',
    'BABA34': 'BABA', 'JDCO34': 'JD', 'BIDU34': 'BIDU',
}

def mapear_ticker_us(ticker_bdr):
    """Mapeia BDR para ticker US"""
    if ticker_bdr in TICKER_MAP:
        return TICKER_MAP[ticker_bdr]
    # Fallback: remover sufixo numérico
    return ticker_bdr.rstrip('0123456789')

def calcular_score_fundamentalista(info):
    """
    Calcula score 0-100 baseado em métricas fundamentalistas
    Retorna: (score, detalhes_dict)
    """
    score = 50  # Base neutra
    detalhes = {
        'pe_ratio': {'valor': None, 'pontos': 0, 'criterio': ''},
        'dividend_yield': {'valor': None, 'pontos': 0, 'criterio': ''},
        'revenue_growth': {'valor': None, 'pontos': 0, 'criterio': ''},
        'recomendacao': {'valor': None, 'pontos': 0, 'criterio': ''},
        'market_cap': {'valor': None, 'pontos': 0, 'criterio': ''},
    }
    
    try:
        # P/E Ratio (15 pontos)
        pe = info.get('trailingPE') or info.get('forwardPE')
        if pe:
            detalhes['pe_ratio']['valor'] = pe
            if 10 <= pe <= 25:
                detalhes['pe_ratio']['pontos'] = 15
                detalhes['pe_ratio']['criterio'] = 'Ótimo (10-25)'
                score += 15
            elif 5 <= pe < 10 or 25 < pe <= 35:
                detalhes['pe_ratio']['pontos'] = 10
                detalhes['pe_ratio']['criterio'] = 'Bom (5-10 ou 25-35)'
                score += 10
            elif pe < 5:
                detalhes['pe_ratio']['pontos'] = 5
                detalhes['pe_ratio']['criterio'] = 'Baixo (<5)'
                score += 5
            elif pe > 50:
                detalhes['pe_ratio']['pontos'] = -10
                detalhes['pe_ratio']['criterio'] = 'Muito alto (>50)'
                score -= 10
            else:
                detalhes['pe_ratio']['criterio'] = 'Regular (35-50)'
        
        # Dividend Yield (10 pontos)
        div_yield = info.get('dividendYield')
        if div_yield:
            detalhes['dividend_yield']['valor'] = div_yield
            if div_yield > 0.04:
                detalhes['dividend_yield']['pontos'] = 10
                detalhes['dividend_yield']['criterio'] = 'Excelente (>4%)'
                score += 10
            elif div_yield > 0.02:
                detalhes['dividend_yield']['pontos'] = 5
                detalhes['dividend_yield']['criterio'] = 'Bom (>2%)'
                score += 5
            else:
                detalhes['dividend_yield']['criterio'] = 'Baixo (<2%)'
        
        # Crescimento de Receita (15 pontos)
        rev_growth = info.get('revenueGrowth')
        if rev_growth:
            detalhes['revenue_growth']['valor'] = rev_growth
            if rev_growth > 0.20:
                detalhes['revenue_growth']['pontos'] = 15
                detalhes['revenue_growth']['criterio'] = 'Excelente (>20%)'
                score += 15
            elif rev_growth > 0.10:
                detalhes['revenue_growth']['pontos'] = 10
                detalhes['revenue_growth']['criterio'] = 'Muito bom (>10%)'
                score += 10
            elif rev_growth > 0.05:
                detalhes['revenue_growth']['pontos'] = 5
                detalhes['revenue_growth']['criterio'] = 'Bom (>5%)'
                score += 5
            elif rev_growth < -0.10:
                detalhes['revenue_growth']['pontos'] = -10
                detalhes['revenue_growth']['criterio'] = 'Negativo (<-10%)'
                score -= 10
            else:
                detalhes['revenue_growth']['criterio'] = 'Estável'
        
        # Recomendação (10 pontos)
        rec = info.get('recommendationKey', '')
        detalhes['recomendacao']['valor'] = rec
        if rec == 'strong_buy':
            detalhes['recomendacao']['pontos'] = 10
            detalhes['recomendacao']['criterio'] = 'Compra Forte'
            score += 10
        elif rec == 'buy':
            detalhes['recomendacao']['pontos'] = 5
            detalhes['recomendacao']['criterio'] = 'Compra'
            score += 5
        elif rec == 'hold':
            detalhes['recomendacao']['criterio'] = 'Manter'
        elif rec == 'sell':
            detalhes['recomendacao']['pontos'] = -5
            detalhes['recomendacao']['criterio'] = 'Venda'
            score -= 5
        elif rec == 'strong_sell':
            detalhes['recomendacao']['pontos'] = -10
            detalhes['recomendacao']['criterio'] = 'Venda Forte'
            score -= 10
        
        # Market Cap (10 pontos)
        mcap = info.get('marketCap')
        if mcap:
            detalhes['market_cap']['valor'] = mcap
            if mcap > 1e12:
                detalhes['market_cap']['pontos'] = 10
                detalhes['market_cap']['criterio'] = 'Mega Cap (>$1T)'
                score += 10
            elif mcap > 100e9:
                detalhes['market_cap']['pontos'] = 5
                detalhes['market_cap']['criterio'] = 'Large Cap (>$100B)'
                score += 5
            elif mcap > 10e9:
                detalhes['market_cap']['criterio'] = 'Mid Cap (>$10B)'
            else:
                detalhes['market_cap']['criterio'] = 'Small Cap (<$10B)'
    
    except Exception:
        pass
    
    return max(0, min(100, score)), detalhes

def buscar_dados_massive_api(ticker_us):
    """
    Busca dados fundamentalistas usando API Massive (mboum.com)
    API Key: VIvP42Yjpz8vkGuCpvIT5Pz2lpdjVdj6
    """
    try:
        url = f"https://api.mboum.com/v1/quote/financials?symbol={ticker_us}&apikey={MASSIVE_API_KEY}"
        response = requests.get(url, timeout=10)
        
        if response.status_code != 200:
            return None
        
        data = response.json()
        
        if not data or (isinstance(data, list) and len(data) == 0):
            return None
        
        # Normalizar dados para formato padrão
        resultado = {
            'marketCap': data.get('marketCap'),
            'trailingPE': data.get('trailingPE'),
            'forwardPE': data.get('forwardPE'),
            'dividendYield': data.get('dividendYield'),
            'revenueGrowth': data.get('revenueGrowth'),
            'recommendationKey': data.get('recommendationMean'),
            'sector': data.get('sector', 'N/A'),
            'industry': data.get('industry', 'N/A'),
        }
        
        return resultado
        
    except Exception:
        return None

def buscar_dados_brapi(ticker_bdr):
    """
    Busca dados da BDR diretamente na BRAPI (B3)
    Retorna dict com dados ou None
    """
    try:
        url = f"https://brapi.dev/api/quote/{ticker_bdr}?token={BRAPI_TOKEN}"
        response = requests.get(url, timeout=10)
        
        if response.status_code != 200:
            return None
        
        data = response.json()
        
        if 'results' not in data or len(data['results']) == 0:
            return None
        
        result = data['results'][0]
        
        # Extrair dados disponíveis
        return {
            'preco': result.get('regularMarketPrice'),
            'variacao': result.get('regularMarketChangePercent'),
            'volume': result.get('regularMarketVolume'),
            'market_cap': result.get('marketCap'),
            'setor': result.get('sector', 'N/A'),
            'nome': result.get('longName', ticker_bdr),
            'cambio': result.get('currency', 'BRL'),
        }
    except Exception:
        return None

def calcular_score_brapi(dados_brapi):
    """
    Calcula score baseado em dados da BRAPI (mais limitados)
    """
    score = 50
    detalhes = {
        'fonte': {'valor': 'BRAPI (B3)', 'pontos': 0, 'criterio': 'Dados da BDR na B3'},
        'market_cap': {'valor': None, 'pontos': 0, 'criterio': ''},
        'volume': {'valor': None, 'pontos': 0, 'criterio': ''},
    }
    
    # Market Cap (20 pontos)
    mcap = dados_brapi.get('market_cap')
    if mcap:
        detalhes['market_cap']['valor'] = mcap
        mcap_b = mcap / 1e9
        if mcap_b > 100:
            detalhes['market_cap']['pontos'] = 20
            detalhes['market_cap']['criterio'] = 'Large Cap (>$100B)'
            score += 20
        elif mcap_b > 10:
            detalhes['market_cap']['pontos'] = 10
            detalhes['market_cap']['criterio'] = 'Mid Cap (>$10B)'
            score += 10
        else:
            detalhes['market_cap']['criterio'] = 'Small Cap (<$10B)'
    
    # Volume (10 pontos - liquidez na B3)
    volume = dados_brapi.get('volume')
    if volume:
        detalhes['volume']['valor'] = volume
        if volume > 1000000:
            detalhes['volume']['pontos'] = 10
            detalhes['volume']['criterio'] = 'Alta liquidez (>1M)'
            score += 10
        elif volume > 100000:
            detalhes['volume']['pontos'] = 5
            detalhes['volume']['criterio'] = 'Boa liquidez (>100K)'
            score += 5
        else:
            detalhes['volume']['criterio'] = 'Baixa liquidez (<100K)'
    
    return max(0, min(100, score)), detalhes

def buscar_dados_fundamentalistas(ticker_bdr):
    """
    Busca dados fundamentalistas usando API Massive
    Fonte única e confiável com chave API dedicada
    """
    try:
        ticker_us = mapear_ticker_us(ticker_bdr)
        
        # Buscar dados via Massive API
        dados = buscar_dados_massive_api(ticker_us)
        
        if dados and (dados.get('marketCap') or dados.get('trailingPE')):
            score, detalhes = calcular_score_fundamentalista(dados)
            
            return {
                'fonte': 'Massive API',
                'ticker_fonte': ticker_us,
                'score': score,
                'detalhes': detalhes,
                'pe_ratio': dados.get('trailingPE') or dados.get('forwardPE'),
                'dividend_yield': dados.get('dividendYield'),
                'market_cap': dados.get('marketCap'),
                'revenue_growth': dados.get('revenueGrowth'),
                'recomendacao': dados.get('recommendationKey'),
                'setor': dados.get('sector', 'N/A'),
                'sucesso': True,
            }
    except Exception:
        pass
    
    return None

# Dicionário de nomes de BDRs (677 empresas - atualizado em 2026-02-06)
NOMES_BDRS = {
    'A1AP34': 'Advance Auto Parts, Inc.',
    'A1DC34': 'Agree Realty Corp',
    'A1DI34': 'Analog Devices, Inc.',
    'A1EP34': 'American Electric Power Company, Inc.',
    'A1ES34': 'AES Corporation',
    'A1FL34': 'Aflac Incorporated',
    'A1IV34': 'Apartment Investment and Management Company',
    'A1KA34': 'Akamai Technologies, Inc.',
    'A1LB34': 'Albemarle Corporation',
    'A1LK34': 'Alaska Air Group, Inc.',
    'A1LL34': 'Bread Financial Holdings, Inc.',
    'A1MD34': 'Advanced Micro Devices, Inc.',
    'A1MP34': 'Ameriprise Financial, Inc.',
    'A1MT34': 'Applied Materials, Inc.',
    'A1NE34': 'Arista Networks Inc',
    'A1PH34': 'Amphenol Corporation',
    'A1PL34': 'Applied Digital Corporation',
    'A1PO34': 'Apollo Global Management Inc',
    'A1PP34': 'AppLovin Corp.',
    'A1RE34': 'Alexandria Real Estate Equities Inc',
    'A1RG34': 'argenx SE ADR',
    'A1SU34': 'Assurant, Inc.',
    'A1TH34': 'Autohome Inc. ADR',
    'A1VB34': 'AvalonBay Communities, Inc.',
    'A1WK34': 'American Water Works Co Inc',
    'A1ZN34': 'AstraZeneca PLC ADR',
    'A2MB34': 'Ambarella, Inc.',
    'A2RR34': 'Arrowhead Pharmaceuticals, Inc.',
    'A2RW34': 'Arrows Electronics Inc',
    'A2SO34': 'Academy Sports and Outdoors Inc',
    'A2XO34': 'Axon Enterprise Inc',
    'A2ZT34': 'Azenta Inc',
    'AADA39': '21Shares Ltd ETP',
    'AALL34': 'American Airlines Group Inc.',
    'AAPL34': 'Apple Inc.',
    'ABBV34': 'AbbVie, Inc.',
    'ABGD39': 'abrdn Gold ETF Trust',
    'ABTT34': 'Abbott Laboratories',
    'ABUD34': 'Anheuser-Busch InBev SA/NV ADR',
    'ACNB34': 'Accenture PLC',
    'ACWX39': 'iShares MSCI ACWI ex US ETF',
    'ADBE34': 'Adobe Inc.',
    'AIRB34': 'Airbnb, Inc.',
    'AMGN34': 'Amgen Inc.',
    'AMZO34': 'Amazon.com, Inc.',
    'APTV34': 'Aptiv PLC',
    'ARGT39': 'Global X MSCI Argentina ETF',
    'ARMT34': 'ArcelorMittal SA',
    'ARNC34': 'Howmet Aerospace Inc',
    'ASML34': 'ASML Holding NV ADR',
    'ATTB34': 'AT&T Inc',
    'AURA33': 'Aura Minerals Inc',
    'AVGO34': 'Broadcom Inc.',
    'AWII34': 'Armstrong World Industries, Inc.',
    'AXPB34': 'American Express Co',
    'B1AM34': 'Brookfield Corporation',
    'B1AX34': 'Baxter International Inc.',
    'B1BW34': 'Bath & Body Works, Inc.',
    'B1CS34': 'Barclays PLC ADR',
    'B1FC34': 'Brown-Forman Corporation',
    'B1IL34': 'Bilibili, Inc. ADR',
    'B1LL34': 'Ball Corporation',
    'B1MR34': 'Biomarin Pharmaceutical Inc.',
    'B1NT34': 'BioNTech SE ADR',
    'B1PP34': 'BP PLC',
    'B1RF34': 'Broadridge Financial Solutions, Inc.',
    'B1SA34': 'Banco Santander Chile ADR',
    'B1TI34': 'British American Tobacco PLC ADR',
    'B2AH34': 'Booz Allen Hamilton Holding Corp Class A',
    'B2HI34': 'BILL Holdings, Inc.',
    'B2LN34': 'BlackLine, Inc.',
    'B2MB34': 'Bumble, Inc.',
    'B2RK34': 'Bruker Corporation',
    'B2UR34': 'Burlington Stores, Inc.',
    'B2YN34': 'Beyond Meat, Inc.',
    'BAAX39': 'iShares MSCI All Country Asia ex Japan ETF',
    'BABA34': 'Alibaba Group Holding Limited ADR',
    'BACW39': 'iShares MSCI ACWI ETF',
    'BAER39': 'iShares U.S. Aerospace & Defense ETF',
    'BAGG39': 'iShares Core U.S. Aggregate Bond ETF',
    'BAIQ39': 'Global X Artificial Intelligence & Technology ETF',
    'BAOR39': 'iShares Core Growth Allocation ETF',
    'BARY39': 'iShares Future AI & Tech ETF',
    'BASK39': '21Shares Ltd ETP',
    'BBER39': 'JPMorgan BetaBuilders Europe Fund',
    'BBJP39': 'JPMorgan BetaBuilders Japan Fund',
    'BBUG39': 'Global X Cybersecurity ETF',
    'BCAT39': 'Global X S&P 500 Catholic Values Custom ETF',
    'BCHI39': 'iShares MSCI China ETF',
    'BCIR39': 'First Trust NASDAQ Cybersecurity ETF',
    'BCLO39': 'Global X Cloud Computing ETF',
    'BCNY39': 'iShares MSCI China A ETF',
    'BCOM39': 'iShares GSCI Commodity Dynamic Roll Strategy ETF',
    'BCPX39': 'Global X Copper Miners ETF',
    'BCSA34': 'Banco Santander SA ADR',
    'BCTE39': 'Global X CleanTech ETF',
    'BCWV39': 'iShares MSCI Global Min Vol Factor ETF',
    'BDVD39': 'Global X Superdividend U.S. ETF',
    'BDVE39': 'iShares Emerging Markets Dividend ETF',
    'BDVY39': 'iShares Select Dividend ETF',
    'BECH39': 'iShares MSCI Chile ETF',
    'BEEM39': 'iShares MSCI Emerging Markets ETF',
    'BEFA39': 'iShares MSCI EAFE ETF',
    'BEFG39': 'iShares MSCI EAFE Growth ETF',
    'BEFV39': 'iShares MSCI EAFE Value ETF',
    'BEGD39': 'iShares ESG Aware MSCI EAFE ETF',
    'BEGE39': 'iShares ESG Aware MSCI EM ETF',
    'BEGU39': 'iShares Trust iShares ESG Aware MSCI USA ETF',
    'BEIS39': 'iShares MSCI Israel ETF',
    'BEMV39': 'iShares MSCI Emerging Markets Min Vol Factor ETF',
    'BEPP39': 'iShares MSCI Pacific ex Japan ETF',
    'BEPU39': 'iShares MSCI Peru and Global Exposure ETF',
    'BERK34': 'Berkshire Hathaway Inc. B',
    'BEWA39': 'iShares MSCI Australia ETF',
    'BEWC39': 'iShares MSCI Canada ETF',
    'BEWD39': 'iShares MSCI Sweden ETF',
    'BEWG39': 'iShares MSCI Germany ETF',
    'BEWH39': 'iShares MSCI Hong Kong ETF',
    'BEWJ39': 'iShares MSCI Japan ETF',
    'BEWL39': 'iShares MSCI Switzerland ETF',
    'BEWP39': 'iShares MSCI Spain ETF',
    'BEWS39': 'iShares MSCI Singapore ETF',
    'BEWW39': 'iShares MSCI Mexico ETF',
    'BEWY39': 'iShares MSCI South Korea Capped ETF',
    'BEWZ39': 'iShares MSCI Brazil ETF',
    'BEZA39': 'iShares MSCI South Africa ETF',
    'BEZU39': 'iShares MSCI Eurozone ETF',
    'BFAV39': 'iShares MSCI EAFE Min Vol Factor ETF',
    'BFLO39': 'iShares Floating Rate Bond ETF',
    'BFXI39': 'iShares China Large-Cap ETF',
    'BGLC39': 'iShares Global 100 ETF',
    'BGOV39': 'iShares US Treasury Bond ETF',
    'BGOZ39': 'iShares 25+ Year Treasury STRIPS Bond ETF',
    'BGRT39': 'iShares Global REIT ETF',
    'BGWH39': 'iShares Core Dividend Growth ETF',
    'BHEF39': 'iShares Currency Hedged MSCI EAFE ETF',
    'BHER39': 'Global X Video Games & Esports ETF',
    'BHVN34': 'Biohaven Research Ltd',
    'BHYC39': 'iShares 0-5 Year High Yield Corporate Bond ETF',
    'BHYG39': 'iShares iBoxx USD High Yield Corporate Bond ETF',
    'BIAI39': 'iShares U.S. Broker-Dealers & Securities Exchanges ETF',
    'BIAU39': 'iShares Gold Trust',
    'BIBB39': 'iShares Biotechnology ETF',
    'BICL39': 'iShares Global Clean Energy ETF',
    'BIDU34': 'Baidu, Inc. ADR',
    'BIEF39': 'iShares Core MSCI EAFE ETF',
    'BIEI39': 'iShares 3-7 Year Treasury Bond ETF',
    'BIEM39': 'iShares Core MSCI Emerging Markets ETF',
    'BIEO39': 'iShares US Oil & Gas Exploration & Production ETF',
    'BIEU39': 'iShares Core MSCI Europe ETF',
    'BIEV39': 'iShares Europe ETF',
    'BIGF39': 'iShares Global Infrastructure ETF',
    'BIGS39': 'iShares 1-5 Year Investment Grade Corporate BondETF',
    'BIHE39': 'iShares US Pharmaceuticals ETF',
    'BIHF39': 'iShares US Healthcare Providers ETF',
    'BIHI39': 'iShares US Medical Devices ETF',
    'BIIB34': 'Biogen Inc.',
    'BIJH39': 'iShares Core S&P Mid-Cap ETF',
    'BIJR39': 'iShares Core S&P Small-Cap ETF',
    'BIJS39': 'iShares S&P Small-Cap 600 Value ETF',
    'BIJT39': 'iShares S&P Small-Cap 600 Growth ETF',
    'BILF39': 'iShares Latin America 40 ETF',
    'BIPC39': 'iShares Core MSCI Pacific ETF',
    'BIPZ39': 'PIMCO Broad US TIPS Index Exchange-Traded Fund',
    'BITB39': 'iShares US Home Construction ETF',
    'BITO39': 'iShares Core S&P Total U.S. Stock Market ETF',
    'BIUS39': 'iShares Core Total USD Bond Market ETF',
    'BIVB39': 'iShares Core S&P 500 ETF',
    'BIVE39': 'iShares S&P 500 Value ETF',
    'BIVW39': 'iShares S&P 500 Growth ETF',
    'BIWF39': 'iShares Russell 1000 Growth ETF',
    'BIWM39': 'iShares Russell 2000 ETF',
    'BIXG39': 'iShares Global Financials ETF',
    'BIXJ39': 'iShares Global Healthcare ETF',
    'BIXN39': 'iShares Global Tech ETF',
    'BIXU39': 'iShares Core MSCI Total International Stock ETF',
    'BIYE39': 'iShares US Energy ETF',
    'BIYF39': 'iShares US Financials ETF',
    'BIYJ39': 'iShares US Industrials ETF',
    'BIYT39': 'iShares 7-10 Year Treasury Bond ETF',
    'BIYW39': 'iShares US Technology ETF',
    'BIYZ39': 'iShares US Telecommunications ETF',
    'BJQU39': 'JPMorgan U.S. Quality Factor ETF',
    'BKCH39': 'Global X Blockchain ETF',
    'BKNG34': 'Booking Holdings Inc.',
    'BKWB39': 'KraneShares CSI China Internet ETF',
    'BKXI39': 'iShares Global Consumer Staples ETF',
    'BLAK34': 'BlackRock, Inc.',
    'BLBT39': 'Global X Lithium & Battery Tech ETF',
    'BLPX39': 'Global X MLP & Energy Infrastructure ETF',
    'BLQD39': 'iShares iBoxx USD Investment Grade Corporate Bond ETF',
    'BMTU39': 'iShares MSCI USA Momentum Factor ETF',
    'BMYB34': 'Bristol-Myers Squibb Company',
    'BNDA39': 'iShares MSCI India ETF',
    'BOAC34': 'Bank of America Corp',
    'BOEF39': 'iShares S&P 100 ETF',
    'BOEI34': 'Boeing Company',
    'BONY34': 'Bank of New York Mellon Corp',
    'BOTZ39': 'Global X Robotics & Artificial Intelligence ETF',
    'BOXP34': 'BXP Inc',
    'BPIC39': 'iShares MSCI Global Metals & Mining Producers ETF',
    'BPVE39': 'Global X US Infrastructure Development ETF',
    'BQQW39': 'First Trust NASDAQ-100 Equal Weighted Index Fund',
    'BQUA39': 'iShares MSCI USA Quality Factor ETF',
    'BQYL39': 'Global X NASDAQ 100 Covered Call ETF',
    'BSCZ39': 'iShares MSCI EAFE Small-Cap ETF',
    'BSDV39': 'Global X Superdividend ETF',
    'BSHV39': 'iShares Short Treasury Bond ETF',
    'BSHY39': 'iShares 1-3 Year Treasury Bond ETF',
    'BSIL39': 'Global X Silver Miners ETF',
    'BSIZ39': 'iShares MSCI USA Size Factor ETF',
    'BSLV39': 'iShares Silver Trust',
    'BSOC39': 'Global X Social Media ETF',
    'BSOX39': 'iShares Semiconductor ETF',
    'BSRE39': 'Global X SuperDividend REIT ETF',
    'BTFL39': 'iShares Treasury Floating Rate Bond ETF',
    'BTIP39': 'iShares TIPS Bond ETF',
    'BTLT39': 'iShares 20+ Year Treasury Bond ETF',
    'BURA39': 'Global X Uranium ETF',
    'BURT39': 'iShares MSCI World ETF',
    'BUSM39': 'iShares MSCI USA Minimum Volatility ETF',
    'BUSR39': 'iShares Core US REIT ETF',
    'BUTL39': 'iShares US Utilities ETF',
    'C1AB34': 'Cable One, Inc.',
    'C1AG34': 'Conagra Brands, Inc.',
    'C1AH34': 'Cardinal Health, Inc.',
    'C1BL34': 'Chubb Limited',
    'C1BR34': 'CBRE Group, Inc.',
    'C1CJ34': 'Cameco Corporation',
    'C1CL34': 'Carnival Corporation',
    'C1CO34': 'Cencora, Inc.',
    'C1DN34': 'Cadence Design Systems, Inc.',
    'C1FG34': 'Citizens Financial Group, Inc.',
    'C1GP34': 'CoStar Group, Inc.',
    'C1HR34': 'C.H.Robinson Worldwide Inc',
    'C1IC34': 'Cigna Group',
    'C1MG34': 'Chipotle Mexican Grill, Inc.',
    'C1MI34': 'Cummins Inc. (Ex. Cummins Engine Inc)',
    'C1MS34': 'CMS Energy Corporation',
    'C1NC34': 'Centene Corporation',
    'C1OO34': 'Cooper Companies, Inc.',
    'C1PB34': 'Campbell\'s Company',
    'C1RH34': 'CRH public limited company',
    'C2AC34': 'CACI International Inc',
    'C2CA34': 'Coca-Cola Femsa SAB de CV ADR',
    'C2GN34': 'Cognex Corp',
    'C2HD34': 'Churchill Downs Inc',
    'C2OI34': 'Coinbase Global, Inc.',
    'C2OL34': 'Grupo Cibest S.A. ADR',
    'C2OU34': 'Coursera Inc',
    'C2RN34': 'Cerence Inc.',
    'C2RS34': 'CRISPR Therapeutics AG',
    'C2RW34': 'CrowdStrike Holdings, Inc.',
    'C2ZR34': 'Caesars Entertainment, Inc.',
    'CAON34': 'Capital One Financial Corp',
    'CATP34': 'Caterpillar Inc',
    'CHCM34': 'Charter Communications, Inc.',
    'CHDC34': 'Church & Dwight Co., Inc.',
    'CHME34': 'CME Group Inc',
    'CHVX34': 'Chevron Corporation',
    'CLOV34': 'Clover Health Investments Corp.',
    'CLXC34': 'Clorox Co',
    'CNIC34': 'Canadian National Railway Co',
    'COCA34': 'Coca-Cola Company',
    'COLG34': 'Colgate-Palmolive Co',
    'COPH34': 'ConocoPhillips',
    'COTY34': 'Coty Inc.',
    'COWC34': 'Costco Wholesale Corporation',
    'CPRL34': 'Canadian Pacific Kansas City Limited',
    'CRIN34': 'Carter\'s Incorporated',
    'CSCO34': 'Cisco Systems, Inc.',
    'CSXC34': 'CSX Corporation',
    'CTGP34': 'Citigroup Inc.',
    'CTSH34': 'Cognizant Technology Solutions Corporation',
    'CVSH34': 'CVS Health Corp',
    'D1DG34': 'Datadog, Inc.',
    'D1EX34': 'DexCom, Inc.',
    'D1LR34': 'Digital Realty Trust, Inc.',
    'D1OC34': 'DocuSign, Inc.',
    'D1OW34': 'Dow, Inc.',
    'D1VN34': 'Devon Energy Corporation',
    'D2AR34': 'Darling Ingredients Inc',
    'D2AS34': 'DoorDash, Inc.',
    'D2NL34': 'Denali Therapeutics Inc',
    'D2OC34': 'Doximity, Inc.',
    'D2OX34': 'Amdocs Ltd',
    'D2PZ34': 'Domino\'s Pizza, Inc.',
    'DBAG34': 'Deutsche Bank AG',
    'DDNB34': 'DuPont de Nemours, Inc.',
    'DEEC34': 'Deere & Co',
    'DEFT31': 'DeFi Technologies Inc',
    'DEOP34': 'Diageo PLC ADR',
    'DGCO34': 'Dollar General Corporation',
    'DHER34': 'Danaher Corp',
    'DISB34': 'Walt Disney Company',
    'DOLL39': 'iShares 0-3 Month Treasury Bond ETF',
    'DTCR39': 'Global X Data Center REITs & Digital Infrastructure ETF',
    'DUOL34': 'Duolingo, Inc.',
    'DVAI34': 'DaVita Inc.',
    'E1CO34': 'Ecopetrol SA ADR',
    'E1DU34': 'New Oriental Education & Technology Group, Inc.',
    'E1LV34': 'Elevance Health, Inc.',
    'E1MN34': 'Eastman Chemical Company',
    'E1MR34': 'Emerson Electric Co.',
    'E1OG34': 'EOG Resources, Inc.',
    'E1QN34': 'Equinor ASA ADR',
    'E1RI34': 'Telefonaktiebolaget LM Ericsson ADR B',
    'E1TN34': 'Eaton Corp. PlcShs',
    'E1WL34': 'Edwards Lifesciences Corp',
    'E2AG34': 'EAGLE MATERIALS INC',
    'E2EF34': 'Euronet Worldwide Inc',
    'E2NP34': 'Enphase Energy, Inc.',
    'E2ST34': 'Elastic NV',
    'E2TS34': 'Etsy, Inc.',
    'EAIN34': 'Electronic Arts Inc.',
    'EBAY34': 'eBay Inc.',
    'EIDO39': 'iShares MSCI Indonesia ETF',
    'ELCI34': 'Estee Lauder Companies Inc',
    'EPHE39': 'iShares MSCI Philippines ETF',
    'EQIX34': 'Equinix Inc',
    'ETHA39': 'iShares Ethereum Trust',
    'EVEB31': 'Eve Holding Inc',
    'EVTC31': 'EVERTEC, Inc.',
    'EWJV39': 'iShares MSCI Japan Value ETF',
    'EXGR34': 'Expedia Group, Inc.',
    'EXPB31': 'Experian PLC Sponsored',
    'EXXO34': 'Exxon Mobil Corp',
    'F1AN34': 'Diamondback Energy, Inc.',
    'F1IS34': 'Fiserv, Inc.',
    'F1MC34': 'FMC Corp',
    'F1NI34': 'Fidelity National Information Services, Inc.',
    'F1SL34': 'Fastly, Inc.',
    'F1TN34': 'Fortinet, Inc.',
    'F2IC34': 'Fair Isaac Corporation',
    'F2IV34': 'Five9 Inc',
    'F2NV34': 'Franco-Nevada Corporation',
    'F2RS34': 'Freshworks, Inc.',
    'FASL34': 'Fastenal Company',
    'FCXO34': 'Freeport-McMoRan, Inc.',
    'FDMO34': 'Ford Motor Company',
    'FDXB34': 'FedEx Corporation',
    'FSLR34': 'First Solar, Inc.',
    'G1AM34': 'Gaming and Leisure Properties Inc',
    'G1AR34': 'Gartner, Inc.',
    'G1DS34': 'GDS Holdings Ltd. ADR A',
    'G1FI34': 'Gold Fields Limited',
    'G1LO34': 'Globant Sa',
    'G1LW34': 'Corning Inc',
    'G1MI34': 'General Mills, Inc.',
    'G1PI34': 'Global Payments Inc.',
    'G1RM34': 'Garmin Ltd.',
    'G1SK34': 'GSK PLC ADR',
    'G1TR39': 'abrdn Precious Metals Basket ETF Trust',
    'G1WW34': 'W.W. Grainger, Inc.',
    'G2DD34': 'GoDaddy, Inc.',
    'G2DI33': 'G2D Investments, Ltd.',
    'G2EV34': 'GE Vernova Inc',
    'GDBR34': 'General Dynamics Corp',
    'GDXB39': 'VanEck Gold Miners ETF',
    'GEOO34': 'GE Aerospace',
    'GILD34': 'Gilead Sciences, Inc',
    'GMCO34': 'General Motors Company',
    'GOGL34': 'Alphabet Inc',
    'GOGL35': 'Alphabet Inc',
    'GPRK34': 'GeoPark Ltd',
    'GPRO34': 'GoPro, Inc.',
    'GPSI34': 'Gap Inc.',
    'GROP31': 'Brazil Potash Corp',
    'GSGI34': 'Goldman Sachs Group, Inc.',
    'H1AS34': 'Hasbro, Inc.',
    'H1CA34': 'HCA Healthcare Inc',
    'H1DB34': 'HDFC Bank Limited',
    'H1II34': 'Huntington Ingalls Industries Inc',
    'H1OG34': 'Harley-Davidson Inc',
    'H1PE34': 'Hewlett Packard Enterprise Co.',
    'H1RL34': 'Hormel Foods Corporation',
    'H1SB34': 'HSBC Holdings Plc',
    'H1UM34': 'Humana Inc',
    'H2TA34': 'Healthcare Realty Trust Incorporated',
    'H2UB34': 'HubSpot, Inc.',
    'HALI34': 'Halliburton Company Shs',
    'HOME34': 'Home Depot Inc',
    'HOND34': 'Honda Motor Co., Ltd. ADR',
    'HPQB34': 'HP Inc.',
    'HYEM39': 'VanEck Emerging Markets High Yield Bond ETF',
    'I1AC34': 'IAC Inc.',
    'I1DX34': 'IDEXX Laboratories, Inc.',
    'I1EX34': 'IDEX Corporation',
    'I1FO34': 'Infosys Limited',
    'I1LM34': 'Illumina, Inc.',
    'I1NC34': 'Incyte Corporation',
    'I1PC34': 'International Paper Company',
    'I1PG34': 'IPG Photonics Corp',
    'I1QV34': 'IQVIA Holdings Inc',
    'I1QY34': 'iQIYI, Inc.',
    'I1RM34': 'Iron Mountain REIT Inc',
    'I1RP34': 'Trane Technologies plc',
    'I1SR34': 'Intuitive Surgical, Inc.',
    'I2NG34': 'Ingredion Inc',
    'I2NV34': 'Invitation Homes, Inc.',
    'IBIT39': 'IShares Bitcoin Trust',
    'IBKR34': 'Interactive Brokers Group, Inc.',
    'ICLR34': 'Icon PLC',
    'INBR32': 'Inter & Co., Inc.',
    'INTU34': 'Intuit Corp',
    'ITLC34': 'Intel Corporation',
    'J1EG34': 'Jacobs Solutions Inc.',
    'J2BL34': 'Jabil Inc.',
    'JBSS32': 'JBS N.V.',
    'JDCO34': 'JD.com, Inc. ADR',
    'JNJB34': 'Johnson & Johnson',
    'JPMC34': 'JPMorgan Chase & Co.',
    'K1BF34': 'KB Financial Group Inc',
    'K1LA34': 'KLA Corporation',
    'K1MX34': 'CarMax, Inc.',
    'K1SG34': 'Keysight Technologies, Inc.',
    'K1SS34': 'Kohl\'s Corporation',
    'K1TC34': 'KT Corporation',
    'K2CG34': 'Kingsoft Cloud Holdings Ltd. ADR',
    'KHCB34': 'Kraft Heinz Company',
    'KMBB34': 'Kimberly-Clark Corp',
    'KMIC34': 'Kinder Morgan Inc',
    'L1EG34': 'Leggett & Platt Inc',
    'L1EN34': 'Lennar Corporation',
    'L1HX34': 'L3Harris Technologies Inc',
    'L1MN34': 'Lumen Technologies, Inc.',
    'L1NC34': 'Lincoln National Corp',
    'L1RC34': 'Lam Research Corporation',
    'L1WH34': 'Lamb Weston Holdings, Inc.',
    'L1YG34': 'Lloyds Banking Group PLC',
    'L1YV34': 'Live Nation Entertainment, Inc.',
    'L2PL34': 'LPL Financial Holdings Inc',
    'L2SC34': 'Lattice Semiconductor Corp',
    'LBRD34': 'Liberty Broadband Corp.',
    'LILY34': 'Eli Lilly & Co',
    'LOWC34': 'Lowe\'s Companies Inc',
    'M1AA34': 'Mid-America Apartment Communities, Inc.',
    'M1CH34': 'Microchip Technology Incorporated',
    'M1CK34': 'McKesson Corporation',
    'M1DB34': 'MongoDB, Inc.',
    'M1HK34': 'Mohawk Industries, Inc.',
    'M1MC34': 'Marsh & McLennan Companies, Inc.',
    'M1NS34': 'Monster Beverage Corporation',
    'M1RN34': 'Moderna, Inc.',
    'M1SC34': 'MSCI Inc.',
    'M1SI34': 'Motorola Solutions, Inc.',
    'M1TA34': 'Meta Platforms Inc',
    'M1TC34': 'Match Group, Inc.',
    'M1TT34': 'Marriott International, Inc. (New)',
    'M1UF34': 'Mitsubishi UFJ Financial Group, Inc.',
    'M2KS34': 'MKS Inc',
    'M2PM34': 'MP Materials Corp',
    'M2PR34': 'Monolithic Power Systems, Inc.',
    'M2PW34': 'Medical Properties Trust, Inc.',
    'M2RV34': 'Marvell Technology, Inc.',
    'M2ST34': 'Strategy Inc',
    'MACY34': 'Macy\'s, Inc.',
    'MCDC34': 'McDonald\'s Corporation',
    'MCOR34': 'Moody\'s Corporation',
    'MDLZ34': 'Mondelez International, Inc.',
    'MDTC34': 'Medtronic plc',
    'MELI34': 'MercadoLibre, Inc.',
    'MKLC34': 'Markel Group Inc.',
    'MMMC34': '3M Company',
    'MOOO34': 'Altria Group, Inc.',
    'MOSC34': 'Mosaic Co',
    'MRCK34': 'Merck & Co., Inc.',
    'MSBR34': 'Morgan Stanley',
    'MSCD34': 'Mastercard Inc',
    'MSFT34': 'Microsoft Corp',
    'MUTC34': 'Micron Technology Inc',
    'N1BI34': 'Neurocrine Biosciences, Inc.',
    'N1CL34': 'Norwegian Cruise Line Holdings Ltd.',
    'N1DA34': 'Nasdaq, Inc.',
    'N1EM34': 'Newmont Corporation',
    'N1GG34': 'National Grid PLC',
    'N1IS34': 'Nisource Inc',
    'N1OW34': 'ServiceNow, Inc.',
    'N1RG34': 'NRG Energy, Inc.',
    'N1TA34': 'NetApp, Inc.',
    'N1UE34': 'Nucor Corporation',
    'N1VO34': 'Novo Nordisk A/S ADR B',
    'N1VR34': 'NVR, Inc.',
    'N1VS34': 'Novartis AG',
    'N1WG34': 'NatWest Group Plc',
    'N1XP34': 'NXP Semiconductors NV',
    'N2ET34': 'Cloudflare Inc',
    'N2LY34': 'Annaly Capital Management, Inc.',
    'N2TN34': 'Nutanix, Inc.',
    'N2VC34': 'NovoCure Ltd.',
    'NETE34': 'Netease Inc ADR',
    'NEXT34': 'NextEra Energy, Inc.',
    'NFLX34': 'Netflix, Inc.',
    'NIKE34': 'NIKE, Inc.',
    'NMRH34': 'Nomura Holdings, Inc. ADR',
    'NOCG34': 'Northrop Grumman Corp.',
    'NOKI34': 'Nokia Oyj',
    'NVDC34': 'NVIDIA Corporation',
    'O1DF34': 'Old Dominion Freight Line, Inc.',
    'O1KT34': 'Okta, Inc.',
    'O2HI34': 'Omega Healthcare Investors Inc',
    'O2NS34': 'ON Semiconductor Corporation',
    'ORCL34': 'Oracle Corp',
    'ORLY34': 'O\'Reilly Automotive Inc',
    'OXYP34': 'Occidental Petroleum Corp',
    'P1AC34': 'PACCAR Inc',
    'P1AY34': 'Paychex, Inc.',
    'P1DD34': 'PDD Holdings Inc. ADR A',
    'P1EA34': 'Healthpeak Properties, Inc.',
    'P1GR34': 'Progressive Corporation',
    'P1KX34': 'POSCO Holdings Inc. ADR',
    'P1LD34': 'Prologis, Inc.',
    'P1NW34': 'Pinnacle West Capital Corp',
    'P1PL34': 'PPL Corporation',
    'P1RG34': 'Perrigo Company PLC',
    'P1SX34': 'Phillips 66',
    'P2AN34': 'Palo Alto Networks, Inc.',
    'P2AT34': 'UiPath, Inc.',
    'P2AX34': 'Patria Investments Ltd.',
    'P2EG34': 'Pegasystems Inc.',
    'P2EN34': 'PENN Entertainment, Inc.',
    'P2IN34': 'Pinterest, Inc.',
    'P2LT34': 'Palantir Technologies Inc.',
    'P2ST34': 'Pure Storage, Inc.',
    'P2TC34': 'PTC Inc.',
    'PAGS34': 'PagSeguro Digital Ltd.',
    'PEPB34': 'PepsiCo, Inc.',
    'PFIZ34': 'Pfizer Inc',
    'PGCO34': 'Procter & Gamble Co',
    'PHGN34': 'Koninklijke Philips N.V. ADR',
    'PHMO34': 'Philip Morris International Inc.',
    'PNCS34': 'PNC Financial Services Group, Inc.',
    'PRXB31': 'Prosus N.V. ADR Sponsored',
    'PSKY34': 'Paramount Skydance Corporation',
    'PYPL34': 'PayPal Holdings, Inc.',
    'Q2SC34': 'QuantumScape Corporation',
    'QCOM34': 'QUALCOMM Incorporated',
    'QUBT34': 'Quantum Computing Inc',
    'R1DY34': 'Dr Reddy\'S Laboratories Ltd ADR',
    'R1EG34': 'Regency Centers Corporation',
    'R1EL34': 'RELX PLC',
    'R1HI34': 'Robert Half Inc.',
    'R1IN34': 'Realty Income Corporation',
    'R1KU34': 'Roku, Inc.',
    'R1MD34': 'ResMed Inc.',
    'R1OP34': 'Roper Technologies, Inc.',
    'R1SG34': 'Republic Services, Inc.',
    'R1YA34': 'Ryanair Holdings PLC',
    'R2BL34': 'Roblox Corp.',
    'R2NG34': 'RingCentral, Inc.',
    'R2PD34': 'Rapid7 Inc',
    'REGN34': 'Regeneron Pharmaceuticals, Inc.Shs',
    'RGTI34': 'Rigetti Computing, Inc.',
    'RIGG34': 'Transocean Ltd.',
    'RIOT34': 'Rio Tinto PLC ADR',
    'ROST34': 'Ross Stores, Inc.',
    'ROXO34': 'Nu Holdings Ltd.',
    'RSSL39': 'Global X RUSSELL 2000 ETF',
    'RYTT34': 'RTX Corporation',
    'S1BA34': 'SBA Communications Corp.',
    'S1BS34': 'Sibanye Stillwater Limited',
    'S1HW34': 'Sherwin-Williams Company',
    'S1KM34': 'SK Telecom Co., Ltd.',
    'S1LG34': 'SL Green Realty Corp.',
    'S1NA34': 'Snap-On Incorporated',
    'S1NP34': 'Synopsys, Inc.',
    'S1OU34': 'Southwest Airlines Co.',
    'S1PO34': 'Spotify Technology S.A.',
    'S1RE34': 'Sempra',
    'S1TX34': 'Seagate Technology Holdings PLC',
    'S1WK34': 'Stanley Black & Decker, Inc.',
    'S1YY34': 'Sysco Corporation',
    'S2CH34': 'Sociedad Quimica y Minera de Chile SA SOQUIMICH ADR',
    'S2EA34': 'Sea Limited ADR A',
    'S2ED34': 'SolarEdge Technologies, Inc.',
    'S2FM34': 'Sprouts Farmers Market, Inc.',
    'S2GM34': 'Sigma Lithium Corporation',
    'S2HO34': 'Shopify, Inc.',
    'S2NA34': 'Snap, Inc.',
    'S2NW34': 'Snowflake, Inc.',
    'S2TA34': 'STAG Industrial, Inc.',
    'S2UI34': 'Sun Communities, Inc.',
    'S2YN34': 'Synaptics Inc',
    'SAPP34': 'SAP SE ADR',
    'SBUB34': 'Starbucks Corporation',
    'SCHW34': 'Charles Schwab Corp',
    'SIVR39': 'abrdn Silver ETF Trust',
    'SLBG34': 'SLB Limited',
    'SLXB39': 'VanEck Steel ETF',
    'SMIN39': 'iShares MSCI India Small Cap Index Fund',
    'SNEC34': 'Sony Group Corporation ADR',
    'SOLN39': '21Shares Ltd ETP',
    'SPGI34': 'S&P Global Inc',
    'SSFO34': 'Salesforce, Inc.',
    'STMN34': 'STMicroelectronics NV ADR',
    'STOC34': 'StoneCo Ltd.',
    'STZB34': 'Constellation Brands, Inc.',
    'T1AL34': 'TAL Education Group ADR A',
    'T1AM34': 'Atlassian Corp',
    'T1EV34': 'Teva Pharmaceutical Industries Ltd',
    'T1LK34': 'PT Telkom Indonesia (Persero) TbkADR B',
    'T1MU34': 'T-Mobile US, Inc.',
    'T1OW34': 'American Tower Corporation',
    'T1RI34': 'TripAdvisor, Inc.',
    'T1SC34': 'Tractor Supply Company',
    'T1SO34': 'Southern Company',
    'T1TW34': 'Take-Two Interactive Software, Inc.',
    'T1WL34': 'Twilio, Inc.',
    'T2DH34': 'Teladoc Health, Inc.',
    'T2ER34': 'Teradyne, Inc.',
    'T2RM34': 'Trimble Inc',
    'T2TD34': 'Trade Desk, Inc.',
    'T2YL34': 'Tyler Technologies Inc',
    'TAKP34': 'Takeda Pharmaceutical Co. Ltd.',
    'TBIL39': 'Global X 1-3 Month T-Bill ETF',
    'TMCO34': 'Toyota Motor Corp ADR',
    'TMOS34': 'Thermo Fisher Scientific Inc.',
    'TOPB39': 'iShares Top 20 US Stocks ETF',
    'TPRY34': 'Tapestry Inc',
    'TRVC34': 'Travelers Companies Inc',
    'TSLA34': 'Tesla, Inc.',
    'TSMC34': 'Taiwan Semiconductor Manufacturing Co., Ltd. ADR',
    'TSNF34': 'Tyson Foods, Inc.',
    'TXSA34': 'Ternium S.A. ADR',
    'U1AI34': 'Under Armour, Inc.',
    'U1AL34': 'United Airlines Holdings, Inc.',
    'U1BE34': 'Uber Technologies, Inc.',
    'U1DR34': 'UDR, Inc.',
    'U1HS34': 'Universal Health Services, Inc.',
    'U1RI34': 'United Rentals, Inc.',
    'U2PS34': 'Upstart Holdings, Inc.',
    'U2PW34': 'Upwork, Inc.',
    'U2ST34': 'Unity Software, Inc.',
    'U2TH34': 'United Therapeutics Corporation',
    'UBSG34': 'UBS Group AG',
    'ULEV34': 'Unilever PLC ADR',
    'UNHH34': 'Unitedhealth Group Inc',
    'UPAC34': 'Union Pacific Corp',
    'USBC34': 'U.S. Bancorp',
    'V1MC34': 'Vulcan Materials Company',
    'V1NO34': 'Vornado Realty Trust',
    'V1OD34': 'Vodafone Group Public Limited Company',
    'V1RS34': 'Verisk Analytics, Inc.',
    'V1RT34': 'Vertiv Holdings LLC',
    'V1ST34': 'Vistra Corp',
    'V1TA34': 'Ventas, Inc.',
    'V2EE34': 'Veeva Systems Inc',
    'V2TX34': 'VTEX',
    'VERZ34': 'Verizon Communications Inc',
    'VISA34': 'Visa Inc.',
    'VLOE34': 'Valero Energy Corp',
    'VRSN34': 'VeriSign, Inc.',
    'W1BD34': 'Warner Bros. Discovery, Inc.',
    'W1BO34': 'Weibo Corp.',
    'W1DC34': 'Western Digital Corporation',
    'W1EL34': 'Welltower Inc.',
    'W1HR34': 'Whirlpool Corporation',
    'W1MB34': 'Williams Companies, Inc.',
    'W1MC34': 'Waste Management, Inc.',
    'W1MG34': 'Warner Music Group Corp.',
    'W1YC34': 'Weyerhaeuser Company',
    'W2ST34': 'West Pharmaceutical Services Inc',
    'W2YF34': 'Wayfair, Inc.',
    'WABC34': 'Western Alliance Bancorp',
    'WALM34': 'Walmart Inc',
    'WFCO34': 'Wells Fargo & Company',
    'WUNI34': 'Western Union Company',
    'X1YZ34': 'Block, Inc.',
    'XPBR31': 'XP Inc.',
    'XRPV39': 'Valour Inc. Structured Product',
    'Y2PF34': 'YPF SA',
    'YUMR34': 'Yum! Brands, Inc.',
    'Z1BR34': 'Zebra Technologies Corporation',
    'Z1OM34': 'Zoom Communications, Inc.',
    'Z1TA34': 'Zeta Global Holdings Corp.',
    'Z1TS34': 'Zoetis, Inc.',
    'Z2LL34': 'Zillow Group, Inc.',
    'Z2SC34': 'Zscaler, Inc.',
}

# --- FUNÇÕES ---

@st.cache_data(ttl=1800)
def buscar_dados(tickers):
    if not tickers: return pd.DataFrame()
    sa_tickers = [f"{t}.SA" for t in tickers]
    try:
        # Mantendo o método que você gosta (rápido)
        df = yf.download(sa_tickers, period=PERIODO, auto_adjust=True, progress=False, timeout=60)
        if df.empty: return pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = pd.MultiIndex.from_tuples([(c[0], c[1].replace(".SA", "")) for c in df.columns])
        return df.dropna(axis=1, how='all')
    except Exception: return pd.DataFrame()

@st.cache_data(ttl=3600)
def obter_nomes_yfinance(tickers):
    """Busca os nomes das empresas diretamente do Yahoo Finance"""
    mapa_nomes = {}
    
    # Processar em lotes pequenos para não sobrecarregar
    total = len(tickers)
    
    if total > 0:
        progresso_nomes = st.progress(0, text="Buscando nomes das empresas...")
        
        for i, ticker in enumerate(tickers):
            try:
                # Atualizar progresso a cada 5 tickers
                if i % 5 == 0:
                    progresso_nomes.progress(min((i + 1) / total, 1.0), 
                                            text=f"Buscando nomes... {i+1}/{total}")
                
                ticker_yf = yf.Ticker(f"{ticker}.SA")
                info = ticker_yf.info
                
                # Tentar pegar o nome na ordem de preferência
                nome = (info.get('longName') or 
                       info.get('shortName') or 
                       ticker)
                
                mapa_nomes[ticker] = nome
            except:
                # Se falhar, usar o ticker mesmo
                mapa_nomes[ticker] = ticker
        
        progresso_nomes.empty()
    
    return mapa_nomes

def calcular_indicadores(df):
    df_calc = df.copy()
    tickers = df_calc.columns.get_level_values(1).unique()
    
    progresso = st.progress(0)
    total = len(tickers)
    
    for i, ticker in enumerate(tickers):
        progresso.progress((i + 1) / total)
        try:
            close = df_calc[('Close', ticker)]
            high = df_calc[('High', ticker)]
            low = df_calc[('Low', ticker)]
            
            # RSI 14
            delta = close.diff()
            ganho = delta.clip(lower=0).rolling(14).mean()
            perda = -delta.clip(upper=0).rolling(14).mean()
            rs = ganho / perda
            df_calc[('RSI14', ticker)] = 100 - (100 / (1 + rs))

            # ESTOCÁSTICO 14 (%K)
            lowest_low = low.rolling(window=14).min()
            highest_high = high.rolling(window=14).max()
            stoch_k = 100 * ((close - lowest_low) / (highest_high - lowest_low))
            df_calc[('Stoch_K', ticker)] = stoch_k

            # Médias e Bollinger
            df_calc[('EMA20', ticker)] = close.ewm(span=20).mean()
            df_calc[('EMA50', ticker)] = close.ewm(span=50).mean()
            df_calc[('EMA200', ticker)] = close.ewm(span=200).mean()
            sma = close.rolling(20).mean()
            std = close.rolling(20).std()
            df_calc[('BB_Lower', ticker)] = sma - (std * 2)
            df_calc[('BB_Upper', ticker)] = sma + (std * 2)

            # MACD
            ema_12 = close.ewm(span=12).mean()
            ema_26 = close.ewm(span=26).mean()
            macd = ema_12 - ema_26
            signal = macd.ewm(span=9).mean()
            df_calc[('MACD_Hist', ticker)] = macd - signal
        except: continue
            
    progresso.empty()
    return df_calc

def calcular_fibonacci(df_ticker):
    try:
        if len(df_ticker) < 50: return None
        high = df_ticker['High'].max()
        low = df_ticker['Low'].min()
        diff = high - low
        return {'61.8%': low + (diff * 0.618)} 
    except: return None

def gerar_sinal(row_ticker, df_ticker):
    sinais = []
    score = 0
    explicacoes = []  # Nova lista para explicações didáticas
    
    def classificar(s):
        if s >= 4: return "Muito Alta"
        if s >= 2: return "Alta"
        if s >= 1: return "Média"
        return "Baixa"

    try:
        close = row_ticker.get('Close')
        rsi = row_ticker.get('RSI14')
        stoch = row_ticker.get('Stoch_K')
        macd_hist = row_ticker.get('MACD_Hist')
        bb_lower = row_ticker.get('BB_Lower')
        
        # Sinais de Reversão
        if pd.notna(rsi):
            if rsi < 30:
                sinais.append("RSI Oversold")
                explicacoes.append(f"📉 RSI em {rsi:.1f} (< 30): Forte sobrevenda, possível reversão iminente")
                score += 3
            elif rsi < 40:
                sinais.append("RSI Baixo")
                explicacoes.append(f"📊 RSI em {rsi:.1f} (< 40): Sobrevenda moderada")
                score += 1
        
        if pd.notna(stoch):
            if stoch < 20:
                sinais.append("Stoch. Fundo")
                explicacoes.append(f"📉 Estocástico em {stoch:.1f} (< 20): Muito sobrevendido, reversão provável")
                score += 2
            
        if pd.notna(macd_hist) and macd_hist > 0:
            sinais.append("MACD Virando")
            explicacoes.append("🔄 MACD positivo: Momentum de alta começando")
            score += 1
            
        if pd.notna(close) and pd.notna(bb_lower):
            if close < bb_lower:
                sinais.append("Abaixo BB")
                explicacoes.append(f"⚠️ Preço abaixo da Banda de Bollinger: Sobrevenda extrema")
                score += 2
            elif close < bb_lower * 1.02:
                sinais.append("Suporte BB")
                explicacoes.append("🎯 Preço próximo da Banda Inferior: Zona de suporte")
                score += 1

        fibo = calcular_fibonacci(df_ticker)
        if fibo and (fibo['61.8%'] * 0.99 <= close <= fibo['61.8%'] * 1.01):
            sinais.append("Fibo 61.8%")
            explicacoes.append("⭐ Preço na Zona de Ouro do Fibonacci (61.8%): Ponto ideal de reversão!")
            score += 2

        return sinais, score, classificar(score), explicacoes
    except:
        return [], 0, "Indefinida", []

def analisar_oportunidades(df_calc, mapa_nomes):
    resultados = []
    tickers = df_calc.columns.get_level_values(1).unique()

    for ticker in tickers:
        try:
            df_ticker = df_calc.xs(ticker, axis=1, level=1).dropna()
            if len(df_ticker) < 50: continue

            last = df_ticker.iloc[-1]
            anterior = df_ticker.iloc[-2]
            
            preco = last.get('Close')
            preco_ant = anterior.get('Close')
            preco_open = last.get('Open')
            volume = last.get('Volume')
            
            if pd.isna(preco) or pd.isna(preco_ant): continue

            # Variações
            queda_dia = ((preco - preco_ant) / preco_ant) * 100
            gap = ((preco_open - preco_ant) / preco_ant) * 100
            
            if queda_dia >= 0: continue 

            sinais, score, classificacao, explicacoes = gerar_sinal(last, df_ticker)
            
            # I.S.
            rsi = last.get('RSI14', 50)
            stoch = last.get('Stoch_K', 50)
            is_index = ((100 - rsi) + (100 - stoch)) / 2

            # === RANKING DE LIQUIDEZ (0-10) ===
            try:
                n = min(20, len(df_ticker))
                vol_serie = df_ticker['Volume'].tail(n)
                vol_medio = vol_serie.mean()
                if pd.isna(vol_medio): vol_medio = 0

                # Gaps: dias em que abertura difere >1% do fechamento anterior
                n_gaps = 0
                for i in range(1, min(n + 1, len(df_ticker))):
                    c_ant = df_ticker['Close'].iloc[-i-1]
                    o_at  = df_ticker['Open'].iloc[-i]
                    if c_ant > 0 and abs((o_at - c_ant) / c_ant) * 100 > 1:
                        n_gaps += 1

                # Consistência: proporção de dias com volume ≥ 80% da média
                consist = sum(1 for v in vol_serie if pd.notna(v) and v >= vol_medio * 0.8) / n if n > 0 else 0

                # Score 0-100
                liq = 0
                # Volume (40 pts)
                if   vol_medio > 500000: liq += 40
                elif vol_medio > 100000: liq += 35
                elif vol_medio >  50000: liq += 30
                elif vol_medio >  10000: liq += 25
                elif vol_medio >   5000: liq += 20
                elif vol_medio >   1000: liq += 15
                elif vol_medio >    100: liq += 10
                else:                    liq += 5
                # Gaps (30 pts — menos é melhor)
                if   n_gaps == 0: liq += 30
                elif n_gaps <= 2: liq += 25
                elif n_gaps <= 5: liq += 20
                elif n_gaps <= 8: liq += 15
                elif n_gaps <=12: liq += 10
                else:             liq += 5
                # Consistência (30 pts)
                if   consist >= 0.75: liq += 30
                elif consist >= 0.50: liq += 20
                elif consist >= 0.25: liq += 10
                else:                 liq += 5

                ranking_liq = max(0, min(10, round(liq / 10)))
            except Exception:
                ranking_liq = 1

            # Tratamento de Nome
            nome_completo = mapa_nomes.get(ticker, ticker)
            
            # Se o nome completo for igual ao ticker, significa que não conseguimos o nome real
            if nome_completo == ticker:
                # Usar o ticker sem processar
                nome_curto = ticker
            else:
                # Processar o nome normalmente
                palavras = nome_completo.split()
                ignore_list = ['INC', 'CORP', 'LTD', 'S.A.', 'GMBH', 'PLC', 'GROUP', 'HOLDINGS', 'CO', 'LLC']
                palavras_uteis = [p for p in palavras if p.upper().replace('.', '').replace(',', '') not in ignore_list]
                
                if len(palavras_uteis) > 0:
                    nome_curto = " ".join(palavras_uteis[:2])
                else:
                    nome_curto = nome_completo
                    
                nome_curto = nome_curto.replace(',', '').title()

            resultados.append({
                'Ticker': ticker,
                'Empresa': nome_curto,
                'Preco': preco,
                'Volume': volume,
                'Queda_Dia': queda_dia,
                'Gap': gap,
                'IS': is_index,
                'RSI14': rsi,
                'Stoch': stoch,
                'Potencial': classificacao,
                'Score': score,
                'Sinais': ", ".join(sinais) if sinais else "-",
                'Explicacoes': explicacoes,
                'Liquidez': int(ranking_liq)
            })
        except: continue
    return resultados

def plotar_grafico(df_ticker, ticker, empresa, rsi, is_val):
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True, gridspec_kw={'height_ratios': [3, 1, 1]})
    
    close = df_ticker['Close']
    ema20 = df_ticker['EMA20']
    ema50 = df_ticker['EMA50'] if 'EMA50' in df_ticker.columns else None
    ema200 = df_ticker['EMA200'] if 'EMA200' in df_ticker.columns else None
    
    # Calcular Fibonacci
    high = df_ticker['High'].max()
    low = df_ticker['Low'].min()
    diff = high - low
    
    # Níveis de Fibonacci (retração)
    fib_levels = {
        '0%': high,
        '23.6%': high - (diff * 0.236),
        '38.2%': high - (diff * 0.382),
        '50%': high - (diff * 0.5),
        '61.8%': high - (diff * 0.618),
        '78.6%': high - (diff * 0.786),
        '100%': low
    }
    
    # Cores para cada nível
    fib_colors = {
        '0%': '#e74c3c',
        '23.6%': '#e67e22',
        '38.2%': '#f39c12',
        '50%': '#3498db',
        '61.8%': '#2ecc71',
        '78.6%': '#1abc9c',
        '100%': '#9b59b6'
    }
    
    # Preço
    ax1 = axes[0]
    ax1.plot(close.index, close.values, label='Close', color='#1E1E1E', linewidth=2, zorder=5)
    
    # Plotar níveis de Fibonacci
    for nivel, preco in fib_levels.items():
        cor = fib_colors[nivel]
        ax1.axhline(preco, color=cor, linestyle='--', linewidth=1, alpha=0.6, zorder=1)
        # Label do nível
        ax1.text(close.index[-1], preco, f' Fib {nivel}', 
                fontsize=8, color=cor, va='center', 
                bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor=cor, alpha=0.7))
    
    # Destacar zona de ouro (61.8%)
    ax1.axhspan(fib_levels['61.8%'] * 0.99, fib_levels['61.8%'] * 1.01, 
                alpha=0.15, color='#2ecc71', zorder=0, label='Zona de Ouro')
    
    # EMA 20 (curto prazo) - Azul
    ax1.plot(close.index, ema20, label='EMA20', alpha=0.9, color='#2962FF', linewidth=1.5, linestyle='-')
    
    # EMA 50 (médio prazo) - Laranja
    if ema50 is not None:
        ax1.plot(close.index, ema50, label='EMA50', alpha=0.8, color='#FF6D00', linewidth=1.5, linestyle='-')
    
    # EMA 200 (longo prazo) - Verde escuro
    if ema200 is not None:
        ax1.plot(close.index, ema200, label='EMA200', alpha=0.7, color='#00695C', linewidth=2, linestyle='-')
    
    # Verificar posição do preço em relação às médias
    ultimo_close = close.iloc[-1]
    ultima_ema20 = ema20.iloc[-1]
    ultima_ema50 = ema50.iloc[-1] if ema50 is not None else 0
    ultima_ema200 = ema200.iloc[-1] if ema200 is not None else 0
    
    # Determinar tendência
    if ema50 is not None and ema200 is not None:
        if ultimo_close > ultima_ema20 > ultima_ema50 > ultima_ema200:
            status = "🟢 Tendência Forte de Alta"
        elif ultimo_close > ultima_ema20 and ultimo_close > ultima_ema50 and ultimo_close > ultima_ema200:
            status = "🟢 Acima das 3 EMAs"
        elif ultimo_close < ultima_ema20 and ultimo_close < ultima_ema50 and ultimo_close < ultima_ema200:
            status = "🔴 Abaixo das 3 EMAs"
        else:
            status = "🟡 Tendência Mista"
    else:
        if ultimo_close > ultima_ema20:
            status = "🟢 Acima EMA20"
        else:
            status = "🔴 Abaixo EMA20"
    
    # Verificar qual nível de Fibonacci está mais próximo
    nivel_mais_proximo = None
    menor_distancia = float('inf')
    for nivel, preco in fib_levels.items():
        distancia = abs(ultimo_close - preco)
        if distancia < menor_distancia:
            menor_distancia = distancia
            nivel_mais_proximo = nivel
    
    # Bollinger Bands (mais discretas)
    ax1.fill_between(close.index, df_ticker['BB_Lower'], df_ticker['BB_Upper'], 
                     alpha=0.08, color='gray', zorder=0)
    
    ax1.set_title(f'{ticker} - {empresa} | I.S.: {is_val:.0f} | {status} | Próx. Fib: {nivel_mais_proximo}', 
                  fontweight='bold', fontsize=10)
    ax1.legend(loc='upper left', fontsize=7, framealpha=0.9, ncol=2)
    ax1.grid(True, alpha=0.2, zorder=0)
    ax1.set_ylabel('Preço (R$)', fontsize=9)

    # RSI
    ax2 = axes[1]
    rsi_values = df_ticker['RSI14']
    ax2.plot(close.index, rsi_values, color='#FF6F00', label='RSI', linewidth=1.5)
    ax2.axhline(30, color='#F44336', linestyle='--', linewidth=1, alpha=0.7)
    ax2.axhline(70, color='#4CAF50', linestyle='--', linewidth=1, alpha=0.7)
    ax2.fill_between(close.index, 0, 30, alpha=0.2, color='#F44336')
    ax2.fill_between(close.index, 70, 100, alpha=0.2, color='#4CAF50')
    ax2.set_ylabel('RSI', fontsize=9)
    ax2.set_ylim(0, 100)
    ax2.grid(True, alpha=0.2)
    
    # Estocástico
    ax3 = axes[2]
    if 'Stoch_K' in df_ticker.columns:
        stoch_values = df_ticker['Stoch_K']
        ax3.plot(close.index, stoch_values, color='#9C27B0', label='Stoch %K', linewidth=1.5)
        ax3.axhline(20, color='#F44336', linestyle='--', linewidth=1, alpha=0.7)
        ax3.axhline(80, color='#4CAF50', linestyle='--', linewidth=1, alpha=0.7)
        ax3.fill_between(close.index, 0, 20, alpha=0.2, color='#F44336')
        ax3.fill_between(close.index, 80, 100, alpha=0.2, color='#4CAF50')
    ax3.set_ylabel('Stoch', fontsize=9)
    ax3.set_ylim(0, 100)
    ax3.grid(True, alpha=0.2)
    ax3.set_xlabel('Data', fontsize=9)
    
    plt.tight_layout()
    return fig

# Estilização
def estilizar_is(val):
    if val >= 75: return 'background-color: #d32f2f; color: white; font-weight: bold'
    elif val >= 60: return 'background-color: #ffa726; color: black'
    else: return 'color: #888888'

def estilizar_potencial(val):
    if val == 'Muito Alta': return 'background-color: #2e7d32; color: white; font-weight: bold' 
    elif val == 'Alta': return 'background-color: #66bb6a; color: black; font-weight: bold'
    elif val == 'Média': return 'background-color: #ffa726; color: black'
    elif val == 'Baixa': return 'background-color: #e0e0e0; color: black' 
    return ''

def estilizar_liquidez(val):
    """Degradê vermelho→amarelo→verde para ranking 0-10"""
    paleta = {
        0:  ('#7f0000', 'white'),
        1:  ('#c62828', 'white'),
        2:  ('#ef5350', 'white'),
        3:  ('#ff7043', 'white'),
        4:  ('#ffa726', 'black'),
        5:  ('#fdd835', 'black'),
        6:  ('#d4e157', 'black'),
        7:  ('#9ccc65', 'black'),
        8:  ('#66bb6a', 'black'),
        9:  ('#2e7d32', 'white'),
        10: ('#1b5e20', 'white'),
    }
    try:
        v = int(val)
    except Exception:
        v = 0
    bg, fg = paleta.get(v, ('#9e9e9e', 'white'))
    return (f'background-color: {bg}; color: {fg}; '
            f'font-weight: 900; font-size: 1.1em; text-align: center;')

def estilizar_fundamentalista(val):
    """Estilo para classificação fundamentalista"""
    cores = {
        '🌟': ('#1b5e20', 'white'),  # Excelente
        '✅': ('#2e7d32', 'white'),   # Bom
        '⚖️': ('#fdd835', 'black'),   # Neutro
        '⚠️': ('#ff7043', 'white'),   # Atenção
        '🔴': ('#c62828', 'white'),   # Evitar
        '—': ('#e0e0e0', 'black'),   # N/A
    }
    bg, fg = cores.get(val, ('#e0e0e0', 'black'))
    return (f'background-color: {bg}; color: {fg}; '
            f'font-weight: 900; font-size: 1.2em; text-align: center;')

# --- LAYOUT DO APP ---

# CSS customizado para aparência profissional
st.markdown("""
<style>
    /* Cabeçalho principal */
    .main-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 10px;
        margin-bottom: 2rem;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    .main-title {
        color: white;
        font-size: 2.5rem;
        font-weight: 700;
        margin: 0;
        text-align: center;
    }
    .main-subtitle {
        color: rgba(255, 255, 255, 0.9);
        font-size: 1.1rem;
        text-align: center;
        margin-top: 0.5rem;
    }
    
    /* Cards de métricas */
    .metric-card {
        background: white;
        padding: 1.5rem;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        border-left: 4px solid #667eea;
    }
    
    /* Melhorar botões */
    .stButton > button {
        width: 100%;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        font-weight: 600;
        border: none;
        padding: 0.75rem 2rem;
        border-radius: 8px;
        transition: all 0.3s ease;
    }
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
    }
    
    /* Melhorar checkboxes */
    .stCheckbox {
        background: white;
        padding: 1rem;
        border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
    }
    
    /* Seções */
    .section-header {
        color: #667eea;
        font-size: 1.5rem;
        font-weight: 600;
        margin-top: 2rem;
        margin-bottom: 1rem;
        padding-bottom: 0.5rem;
        border-bottom: 2px solid #667eea;
    }
    
    /* Tabela */
    .dataframe {
        border-radius: 8px;
        overflow: hidden;
    }
    
    /* Info boxes */
    .stAlert {
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)

# Cabeçalho profissional
from datetime import datetime
import pytz

# Obter data e hora do Brasil
fuso_brasil = pytz.timezone('America/Sao_Paulo')
agora = datetime.now(fuso_brasil)
data_hora_analise = agora.strftime("%d/%m/%Y às %H:%M:%S")
dia_semana = agora.strftime("%A")
dias_pt = {
    'Monday': 'Segunda-feira',
    'Tuesday': 'Terça-feira', 
    'Wednesday': 'Quarta-feira',
    'Thursday': 'Quinta-feira',
    'Friday': 'Sexta-feira',
    'Saturday': 'Sábado',
    'Sunday': 'Domingo'
}
dia_semana_pt = dias_pt.get(dia_semana, dia_semana)

st.markdown(f"""
<div class="main-header">
    <h1 class="main-title">📊 Monitor BDR - Swing Trade Pro</h1>
    <p class="main-subtitle">Análise Técnica Avançada | Rastreamento de Oportunidades em Tempo Real</p>
    <p style="color: rgba(255, 255, 255, 0.8); font-size: 0.9rem; text-align: center; margin-top: 0.5rem;">
        🕐 {dia_semana_pt}, {data_hora_analise} (Horário de Brasília)
    </p>
</div>
""", unsafe_allow_html=True)

# Barra de informações
col_info1, col_info2, col_info3 = st.columns(3)
with col_info1:
    st.markdown("**📈 Estratégia:** Reversão em Sobrevenda")
with col_info2:
    st.markdown("**🎯 Foco:** BDRs em Queda com Potencial")
with col_info3:
    st.markdown("**⏱️ Timeframe:** 6 Meses | Diário")

st.markdown("---")

# Seção educacional (expansível)
with st.expander("📚 Guia dos Indicadores - Entenda os Sinais", expanded=False):
    st.markdown("""
    ### 🎯 Índice de Sobrevenda (I.S.)
    **O que é:** Combina RSI e Estocástico para medir o nível de sobrevenda.
    - **75-100**: 🔴 Muito sobrevendido (alta probabilidade de reversão)
    - **60-75**: 🟠 Sobrevendido moderado
    - **< 60**: ⚪ Não sobrevendido
    
    ### 📉 RSI (Relative Strength Index)
    **O que é:** Mede a força do movimento de preço (0-100).
    - **< 30**: 🟢 Zona de sobrevenda (possível reversão para alta)
    - **30-70**: Zona neutra
    - **> 70**: 🔴 Zona de sobrecompra (possível reversão para baixa)
    
    ### 📊 Estocástico
    **O que é:** Compara o preço de fechamento com a faixa de preços recente.
    - **< 20**: 🟢 Muito sobrevendido (sinal de compra potencial)
    - **20-80**: Zona neutra
    - **> 80**: 🔴 Sobrecomprado (cuidado)
    
    ### 📈 MACD (Moving Average Convergence Divergence)
    **O que é:** Mostra a relação entre duas médias móveis.
    - **Virando positivo**: 🟢 Momento de alta começando
    - **Histograma crescente**: Força compradora aumentando
    
    ### 🎨 Bandas de Bollinger
    **O que é:** Envelope de volatilidade ao redor da média.
    - **Preço abaixo da banda inferior**: 🟢 Sobrevendido (possível reversão)
    - **Preço na banda superior**: 🔴 Sobrecomprado
    
    ### 🌟 Fibonacci (61.8% - Zona de Ouro)
    **O que é:** Níveis onde o preço tende a encontrar suporte/resistência.
    - **61.8%**: ⭐ Nível mais importante - alta probabilidade de reversão
    - **38.2% e 50%**: Suportes intermediários
    - **Próximo de um nível**: Atenção para possível reversão
    
    ### 📊 Médias Móveis (EMAs)
    **O que é:** Mostram a direção da tendência.
    - **Preço acima das 3 EMAs**: 🟢 Tendência de alta consolidada
    - **EMA20 > EMA50 > EMA200**: Alinhamento de alta (ideal!)
    - **Preço caindo MAS acima das EMAs**: 📈 Correção em tendência de alta (oportunidade!)
    
    ### 💡 Como Usar Este Monitor
    1. **Filtre** por EMAs para encontrar correções em tendências de alta
    2. **Procure** I.S. alto (>75) = forte sobrevenda
    3. **Confirme** com RSI < 30 e Estocástico < 20
    4. **Verifique** se está próximo de Fibonacci 61.8%
    5. **Entre** na zona de ouro e aguarde a reversão! 🚀
    """)

st.markdown("---")

if st.button("🔄 Atualizar Análise", type="primary"):
    with st.spinner("Conectando à API e baixando dados..."):
        # Usar dicionário local de BDRs em vez de buscar da BRAPI
        lista_bdrs = list(NOMES_BDRS.keys())
        
        df = buscar_dados(lista_bdrs)
        
        if df.empty:
            st.error("Erro ao carregar dados. Se o Yahoo tiver bloqueado, aguarde alguns minutos.")
            st.stop()
        
    # Calcular indicadores
    with st.spinner("Calculando indicadores técnicos..."):
        df_calc = calcular_indicadores(df)
        
    # Analisar oportunidades usando dicionário local
    with st.spinner("Analisando oportunidades..."):
        oportunidades = analisar_oportunidades(df_calc, NOMES_BDRS)
        
        if oportunidades:
            # Atualizar os nomes nas oportunidades (já processados em analisar_oportunidades)
            # Salvar no session_state
            st.session_state['oportunidades'] = oportunidades
            st.session_state['df_calc'] = df_calc

# Verificar se há dados no session_state
if 'oportunidades' in st.session_state and 'df_calc' in st.session_state:
    oportunidades = st.session_state['oportunidades']
    df_calc = st.session_state['df_calc']
    
    # Criar DataFrame das oportunidades
    df_res = pd.DataFrame(oportunidades)
    df_res = df_res.sort_values(by='Queda_Dia', ascending=True)
    
    st.success(f"✅ {len(oportunidades)} oportunidades detectadas!")
    
    # --- FILTROS COM DESIGN PROFISSIONAL ---
    st.markdown('<h3 class="section-header">🎯 Filtros de Tendência</h3>', unsafe_allow_html=True)
    
    st.markdown("""
    <div style='background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%); 
                padding: 1rem; border-radius: 8px; margin-bottom: 1rem;'>
        <p style='margin: 0; color: #334155; font-weight: 500;'>
            💡 <strong>Dica:</strong> Selecione as médias móveis para filtrar BDRs em correção dentro de tendências de alta
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    col_filtro1, col_filtro2, col_filtro3 = st.columns(3)
    
    with col_filtro1:
        filtrar_ema20 = st.checkbox(
            "📈 Acima da EMA20", 
            value=False,
            help="Preço acima da EMA20 (curto prazo)"
        )
    
    with col_filtro2:
        filtrar_ema50 = st.checkbox(
            "📊 Acima da EMA50", 
            value=False,
            help="Preço acima da EMA50 (médio prazo)"
        )
    
    with col_filtro3:
        filtrar_ema200 = st.checkbox(
            "📉 Acima da EMA200", 
            value=False,
            help="Preço acima da EMA200 (longo prazo)"
        )

    # Slider de liquidez
    st.markdown("**💧 Liquidez mínima:**")
    ranking_min_liq = st.slider(
        "0 = sem filtro  |  10 = máxima exigência",
        min_value=0, max_value=10, value=0, step=1,
        help="Filtra BDRs pelo ranking de liquidez 0-10. Quanto maior, menor o risco de gaps e volume baixo."
    )
    
    # Aplicar filtros se algum selecionado
    if filtrar_ema20 or filtrar_ema50 or filtrar_ema200 or ranking_min_liq > 0:
        df_res_filtrado = []
        contadores = {'ema20': 0, 'ema50': 0, 'ema200': 0, 'sem_dados': 0}
        
        for opp in oportunidades:
            ticker = opp['Ticker']
            try:
                df_ticker = df_calc.xs(ticker, axis=1, level=1).dropna()
                
                # Verificar tamanho mínimo
                tam = len(df_ticker)
                if tam < 20:
                    contadores['sem_dados'] += 1
                    continue
                
                ultimo_close = df_ticker['Close'].iloc[-1]
                
                # Verificar cada condição separadamente
                passa_filtro = True
                
                # Filtro EMA20
                if filtrar_ema20:
                    if 'EMA20' in df_ticker.columns and tam >= 20:
                        ultima_ema20 = df_ticker['EMA20'].iloc[-1]
                        if pd.notna(ultima_ema20) and ultimo_close > ultima_ema20:
                            contadores['ema20'] += 1
                        else:
                            passa_filtro = False
                    else:
                        passa_filtro = False
                
                # Filtro EMA50
                if filtrar_ema50 and passa_filtro:
                    if 'EMA50' in df_ticker.columns and tam >= 50:
                        ultima_ema50 = df_ticker['EMA50'].iloc[-1]
                        if pd.notna(ultima_ema50) and ultimo_close > ultima_ema50:
                            contadores['ema50'] += 1
                        else:
                            passa_filtro = False
                    else:
                        passa_filtro = False
                
                # Filtro EMA200
                if filtrar_ema200 and passa_filtro:
                    # EMA200 precisa de pelo menos 50 períodos para ser significativa
                    if 'EMA200' in df_ticker.columns and tam >= 50:
                        ultima_ema200 = df_ticker['EMA200'].iloc[-1]
                        if pd.notna(ultima_ema200) and ultimo_close > ultima_ema200:
                            contadores['ema200'] += 1
                        else:
                            passa_filtro = False
                    else:
                        passa_filtro = False

                # Filtro de Liquidez
                if ranking_min_liq > 0 and passa_filtro:
                    if opp.get('Liquidez', 0) < ranking_min_liq:
                        passa_filtro = False
                
                # Adicionar se passou em todos os filtros
                if passa_filtro:
                    df_res_filtrado.append(opp)
                    
            except Exception as e:
                contadores['sem_dados'] += 1
                continue
        
        if df_res_filtrado:
            df_res = pd.DataFrame(df_res_filtrado)
            df_res = df_res.sort_values(by='Queda_Dia', ascending=True)
            
            # Mensagem personalizada com estatísticas
            filtros_ativos = []
            if filtrar_ema20:
                filtros_ativos.append(f"EMA20 ({contadores['ema20']} ✓)")
            if filtrar_ema50:
                filtros_ativos.append(f"EMA50 ({contadores['ema50']} ✓)")
            if filtrar_ema200:
                filtros_ativos.append(f"EMA200 ({contadores['ema200']} ✓)")
            
            st.markdown(f"""
            <div style='background: linear-gradient(135deg, #d4fc79 0%, #96e6a1 100%); 
                        padding: 1rem; border-radius: 8px; margin: 1rem 0;'>
                <p style='margin: 0; color: #166534; font-weight: 600; font-size: 1.1rem;'>
                    ✅ {len(df_res)} BDRs encontradas | Filtros ativos: {' + '.join(filtros_ativos)}
                </p>
            </div>
            """, unsafe_allow_html=True)
        else:
            # Mostrar estatísticas de debug
            filtros_ativos = []
            if filtrar_ema20:
                filtros_ativos.append(f"EMA20 ({contadores['ema20']} acima)")
            if filtrar_ema50:
                filtros_ativos.append(f"EMA50 ({contadores['ema50']} acima)")
            if filtrar_ema200:
                filtros_ativos.append(f"EMA200 ({contadores['ema200']} acima)")
            
            st.markdown(f"""
            <div style='background: linear-gradient(135deg, #ffeaa7 0%, #fdcb6e 100%); 
                        padding: 1rem; border-radius: 8px; margin: 1rem 0;'>
                <p style='margin: 0; color: #7c3626; font-weight: 600;'>
                    ⚠️ Nenhuma BDR passou em TODOS os filtros combinados
                </p>
                <p style='margin: 0.5rem 0 0 0; color: #7c3626; font-size: 0.9rem;'>
                    📊 {' | '.join(filtros_ativos)} | {contadores['sem_dados']} sem dados suficientes
                </p>
            </div>
            """, unsafe_allow_html=True)
            df_res = pd.DataFrame()  # DataFrame vazio
    
    if not df_res.empty:
        # --- TABELA INTERATIVA ---
        st.markdown('<h3 class="section-header">📊 Oportunidades Detectadas</h3>', unsafe_allow_html=True)
        
        st.markdown("""
        <div style='background: #f8fafc; padding: 0.75rem; border-radius: 6px; margin-bottom: 1rem; border-left: 4px solid #667eea;'>
            <p style='margin: 0; color: #475569; font-size: 0.95rem;'>
                💡 <strong>Dica:</strong> Clique em qualquer linha da tabela para visualizar o gráfico técnico completo
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        evento = st.dataframe(
            df_res.style.map(estilizar_potencial, subset=['Potencial'])
                        .map(estilizar_is, subset=['IS'])
                        .map(estilizar_liquidez, subset=['Liquidez'])
            .format({
                'Preco': 'R$ {:.2f}',
                'Volume': '{:,.0f}',
                'Queda_Dia': '{:.2f}%',
                'Gap': '{:.2f}%',
                'IS': '{:.0f}',
                'RSI14': '{:.0f}',
                'Stoch': '{:.0f}',
                'Liquidez': '{:.0f}'
            }),
            column_order=("Ticker", "Empresa", "Liquidez", "Preco", "Queda_Dia", "IS", "Volume", "Gap", "Potencial", "Score", "Sinais"),
            column_config={
                "Empresa": st.column_config.TextColumn("Empresa", width="medium"),
                "Liquidez": st.column_config.NumberColumn("💧 Liq.", width="small",
                    help="Ranking de Liquidez 0-10 (🔴 baixa → 🟢 alta)"),
                "IS": st.column_config.NumberColumn("I.S.", help="Índice de Sobrevenda"),
                "Volume": st.column_config.NumberColumn("Vol.", help="Volume Financeiro"),
                "Score": st.column_config.ProgressColumn("Força", format="%d", min_value=0, max_value=10),
                "Potencial": st.column_config.Column("Sinal"),
                "Sinais": st.column_config.TextColumn("Sinais Técnicos", width="large")
            },
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row"
        )
        
        # --- GRÁFICO INTERATIVO ---
        if evento.selection and evento.selection.rows:
            st.markdown("---")
            linha_selecionada = evento.selection.rows[0]
            row = df_res.iloc[linha_selecionada]
            ticker = row['Ticker']
            
            st.markdown(f'<h3 class="section-header">📈 Análise Técnica: {ticker} - {row["Empresa"]}</h3>', unsafe_allow_html=True)
            
            try:
                df_ticker = df_calc.xs(ticker, axis=1, level=1).dropna()
                
                # Layout: gráfico maior à esquerda, info à direita
                col1, col2 = st.columns([3, 1])
                
                with col1:
                    fig = plotar_grafico(df_ticker, ticker, row['Empresa'], row['RSI14'], row['IS'])
                    st.pyplot(fig)
                
                with col2:
                    potencial = row['Potencial']
                    
                    # Card de potencial
                    if "Alta" in potencial:
                        cor_bg = "linear-gradient(135deg, #d4fc79 0%, #96e6a1 100%)"
                        cor_texto = "#166534"
                        icone = "🟢"
                    elif "Média" in potencial:
                        cor_bg = "linear-gradient(135deg, #ffeaa7 0%, #fdcb6e 100%)"
                        cor_texto = "#7c3626"
                        icone = "🟡"
                    else:
                        cor_bg = "linear-gradient(135deg, #dfe6e9 0%, #b2bec3 100%)"
                        cor_texto = "#2d3436"
                        icone = "⚪"
                    
                    st.markdown(f"""
                    <div style='background: {cor_bg}; padding: 1rem; border-radius: 8px; margin-bottom: 1rem;'>
                        <h2 style='margin: 0; color: {cor_texto}; text-align: center;'>
                            {icone} {potencial}
                        </h2>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    st.metric("💰 Preço Atual", f"R$ {row['Preco']:.2f}")
                    st.metric("📉 Queda no Dia", f"{row['Queda_Dia']:.2f}%", delta_color="inverse")
                    st.metric("🎯 I.S. (Sobrevenda)", f"{row['IS']:.0f}/100")
                    
                    if row['Gap'] < -1:
                        st.metric("⚡ Gap de Abertura", f"{row['Gap']:.2f}%", delta_color="inverse")
                    
                    st.markdown(f"**⭐ Score:** {row['Score']}/10")
                    st.markdown(f"**📊 Volume:** {row['Volume']:,.0f}")
                    
                    # Sinais técnicos
                    st.markdown("""
                    <div style='background: #e0e7ff; padding: 0.75rem; border-radius: 6px; margin-top: 1rem;'>
                        <p style='margin: 0; font-weight: 600; color: #3730a3; font-size: 0.9rem;'>
                            📋 Sinais Detectados
                        </p>
                    </div>
                    """, unsafe_allow_html=True)
                    st.markdown(f"<p style='font-size: 0.85rem; color: #475569;'>{row['Sinais']}</p>", unsafe_allow_html=True)
                    
                    # Explicações didáticas
                    if 'Explicacoes' in row and row['Explicacoes']:
                        st.markdown("""
                        <div style='background: #fef3c7; padding: 0.75rem; border-radius: 6px; margin-top: 1rem;'>
                            <p style='margin: 0; font-weight: 600; color: #92400e; font-size: 0.9rem;'>
                                💡 O que isso significa?
                            </p>
                        </div>
                        """, unsafe_allow_html=True)
                        for explicacao in row['Explicacoes']:
                            st.markdown(f"<p style='font-size: 0.82rem; color: #92400e; margin: 0.3rem 0;'>• {explicacao}</p>", unsafe_allow_html=True)
                    
            except Exception as e:
                st.error(f"❌ Erro ao carregar gráfico: {e}")
            
            # === PAINEL FUNDAMENTALISTA (ABAIXO DO GRÁFICO) ===
            st.markdown("---")
            st.markdown('<h3 class="section-header">📊 Análise Fundamentalista</h3>', unsafe_allow_html=True)
            
            with st.spinner(f"Buscando dados fundamentalistas de {ticker}..."):
                fund_data = buscar_dados_fundamentalistas(ticker)
            
            if fund_data:
                # Card com score em porcentagem
                score = fund_data['score']
                fonte = fund_data.get('fonte', 'Yahoo Finance')
                ticker_fonte = fund_data.get('ticker_fonte', ticker)
                
                if score >= 80:
                    cor_fundo = "linear-gradient(135deg, #d4fc79 0%, #96e6a1 100%)"
                    cor_texto = "#166534"
                    label = "EXCELENTE"
                elif score >= 65:
                    cor_fundo = "linear-gradient(135deg, #a7f3d0 0%, #6ee7b7 100%)"
                    cor_texto = "#065f46"
                    label = "BOM"
                elif score >= 50:
                    cor_fundo = "linear-gradient(135deg, #fde047 0%, #fbbf24 100%)"
                    cor_texto = "#92400e"
                    label = "NEUTRO"
                elif score >= 35:
                    cor_fundo = "linear-gradient(135deg, #fdcb6e 0%, #ff7043 100%)"
                    cor_texto = "#7c3626"
                    label = "ATENÇÃO"
                else:
                    cor_fundo = "linear-gradient(135deg, #ef5350 0%, #c62828 100%)"
                    cor_texto = "white"
                    label = "EVITAR"
                
                st.markdown(f"""
                <div style='background: {cor_fundo}; padding: 1.5rem; border-radius: 12px; margin-bottom: 1.5rem;'>
                    <div style='text-align: center;'>
                        <h1 style='margin: 0; color: {cor_texto}; font-size: 4rem; font-weight: 900;'>{score:.0f}%</h1>
                        <p style='margin: 0.5rem 0 0 0; color: {cor_texto}; font-size: 1.5rem; font-weight: 600;'>
                            {label}
                        </p>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # Fonte dos dados
                if 'BRAPI' in fonte:
                    st.info(f"📡 **Fonte:** {fonte} | Ticker: **{ticker_fonte}**\n\n⚠️ *Dados limitados disponíveis para esta BDR. Score baseado em Market Cap e Volume na B3.*")
                else:
                    st.success(f"📡 **Fonte:** {fonte} | Ticker US: **{ticker_fonte}**")
                
                # Métricas em colunas
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.markdown("### 📈 Valuation")
                    if fund_data.get('pe_ratio'):
                        st.metric("P/E Ratio", f"{fund_data['pe_ratio']:.2f}")
                    else:
                        st.metric("P/E Ratio", "N/A")
                    
                    if fund_data.get('market_cap'):
                        mcap_b = fund_data['market_cap'] / 1e9
                        if mcap_b >= 1000:
                            st.metric("Market Cap", f"${mcap_b/1000:.2f}T")
                        else:
                            st.metric("Market Cap", f"${mcap_b:.1f}B")
                    else:
                        st.metric("Market Cap", "N/A")
                
                with col2:
                    st.markdown("### 💰 Rentabilidade")
                    if fund_data.get('dividend_yield'):
                        st.metric("Dividend Yield", f"{fund_data['dividend_yield']*100:.2f}%")
                    else:
                        st.metric("Dividend Yield", "N/A")
                    
                    if fund_data.get('revenue_growth'):
                        growth = fund_data['revenue_growth'] * 100
                        st.metric("Crescimento Receita", f"{growth:+.1f}%",
                                 delta=f"{growth:.1f}%" if growth > 0 else None)
                    elif fund_data.get('volume_b3'):
                        st.metric("Volume B3", f"{fund_data['volume_b3']:,.0f}")
                    else:
                        st.metric("Crescimento Receita", "N/A")
                
                with col3:
                    st.markdown("### 🎯 Info")
                    rec = fund_data.get('recomendacao')
                    if rec and rec != 'N/A':
                        rec_map = {
                            'strong_buy': ('🟢 COMPRA FORTE', 'green'),
                            'buy': ('🟢 Compra', 'green'),
                            'hold': ('🟡 Manter', 'orange'),
                            'sell': ('🔴 Venda', 'red'),
                            'strong_sell': ('🔴 VENDA FORTE', 'red'),
                        }
                        rec_texto, rec_cor = rec_map.get(rec, (rec.upper(), 'gray'))
                        st.markdown(f"**Analistas:**")
                        st.markdown(f"<h3 style='color: {rec_cor}; margin: 0;'>{rec_texto}</h3>", unsafe_allow_html=True)
                    
                    if fund_data.get('setor') and fund_data['setor'] != 'N/A':
                        st.markdown(f"**Setor:**")
                        st.markdown(f"<p style='font-size: 1.1rem; margin: 0;'>{fund_data['setor']}</p>", unsafe_allow_html=True)
                    else:
                        st.markdown("**Setor:** N/A")
                
                # Detalhamento da Pontuação
                st.markdown("---")
                st.markdown("### 📋 Detalhamento da Pontuação")
                
                detalhes = fund_data.get('detalhes', {})
                
                # Criar tabela de detalhamento
                dados_tabela = []
                
                # Verificar se tem dados BRAPI ou Yahoo
                if 'fonte' in detalhes and 'BRAPI' in detalhes['fonte'].get('valor', ''):
                    # Dados da BRAPI
                    fonte_det = detalhes.get('fonte', {})
                    dados_tabela.append({
                        'Métrica': 'Fonte de Dados',
                        'Valor': fonte_det.get('valor', 'BRAPI'),
                        'Pontos': '-',
                        'Avaliação': fonte_det.get('criterio', 'Dados da B3')
                    })
                    
                    mcap_det = detalhes.get('market_cap', {})
                    if mcap_det.get('valor'):
                        mcap_val = mcap_det['valor'] / 1e9
                        if mcap_val >= 1000:
                            valor_str = f"${mcap_val/1000:.2f}T"
                        else:
                            valor_str = f"${mcap_val:.1f}B"
                        dados_tabela.append({
                            'Métrica': 'Market Cap',
                            'Valor': valor_str,
                            'Pontos': f"{mcap_det['pontos']:+d}/20",
                            'Avaliação': mcap_det.get('criterio', '-')
                        })
                    
                    vol_det = detalhes.get('volume', {})
                    if vol_det.get('valor'):
                        dados_tabela.append({
                            'Métrica': 'Volume B3',
                            'Valor': f"{vol_det['valor']:,.0f}",
                            'Pontos': f"{vol_det['pontos']:+d}/10",
                            'Avaliação': vol_det.get('criterio', '-')
                        })
                else:
                    # Dados do Yahoo Finance (completos)
                    pe_det = detalhes.get('pe_ratio', {})
                    if pe_det.get('valor'):
                        dados_tabela.append({
                            'Métrica': 'P/E Ratio',
                            'Valor': f"{pe_det['valor']:.2f}",
                            'Pontos': f"{pe_det['pontos']:+d}/15",
                            'Avaliação': pe_det.get('criterio', '-')
                        })
                    
                    div_det = detalhes.get('dividend_yield', {})
                    if div_det.get('valor'):
                        dados_tabela.append({
                            'Métrica': 'Dividend Yield',
                            'Valor': f"{div_det['valor']*100:.2f}%",
                            'Pontos': f"{div_det['pontos']:+d}/10",
                            'Avaliação': div_det.get('criterio', '-')
                        })
                    
                    rev_det = detalhes.get('revenue_growth', {})
                    if rev_det.get('valor') is not None:
                        dados_tabela.append({
                            'Métrica': 'Crescimento Receita',
                            'Valor': f"{rev_det['valor']*100:+.1f}%",
                            'Pontos': f"{rev_det['pontos']:+d}/15",
                            'Avaliação': rev_det.get('criterio', '-')
                        })
                    
                    rec_det = detalhes.get('recomendacao', {})
                    if rec_det.get('valor'):
                        dados_tabela.append({
                            'Métrica': 'Recomendação Analistas',
                            'Valor': rec_det['valor'].replace('_', ' ').title(),
                            'Pontos': f"{rec_det['pontos']:+d}/10",
                            'Avaliação': rec_det.get('criterio', '-')
                        })
                    
                    mcap_det = detalhes.get('market_cap', {})
                    if mcap_det.get('valor'):
                        mcap_val = mcap_det['valor'] / 1e9
                        if mcap_val >= 1000:
                            valor_str = f"${mcap_val/1000:.2f}T"
                        else:
                            valor_str = f"${mcap_val:.1f}B"
                        dados_tabela.append({
                            'Métrica': 'Market Cap',
                            'Valor': valor_str,
                            'Pontos': f"{mcap_det['pontos']:+d}/10",
                            'Avaliação': mcap_det.get('criterio', '-')
                        })
                
                if dados_tabela:
                    df_detalhes = pd.DataFrame(dados_tabela)
                    st.dataframe(
                        df_detalhes,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Métrica": st.column_config.TextColumn("Métrica", width="medium"),
                            "Valor": st.column_config.TextColumn("Valor Atual", width="small"),
                            "Pontos": st.column_config.TextColumn("Pontos", width="small"),
                            "Avaliação": st.column_config.TextColumn("Avaliação", width="medium"),
                        }
                    )
                    
                    st.caption(f"**Score Total:** {score:.0f}/100 (Base: 50 + Bônus/Penalidades)")
                else:
                    st.warning("Não há detalhes disponíveis para esta análise.")
                
            else:
                st.warning(f"⚠️ Não foi possível obter dados fundamentalistas para {ticker}")
                ticker_us = mapear_ticker_us(ticker)
                st.info(f"""
                💡 **Por que isso acontece?**
                
                - Ticker BDR: `{ticker}`
                - Ticker US mapeado: `{ticker_us}`
                
                **Tentativas realizadas:**
                1. ❌ Yahoo Finance (empresa mãe) - Sem dados
                2. ❌ BRAPI (BDR na B3) - Sem dados
                
                **Possíveis causas:**
                - BDR muito nova ou com baixíssimo volume
                - Ticker não listado ou delisted
                - Dados ainda não disponíveis nas APIs públicas
                
                **Solução:** Infelizmente este ticker não possui dados fundamentalistas disponíveis nas fontes consultadas.
                """)
                
        else:
            st.markdown("""
            <div style='background: linear-gradient(135deg, #e0e7ff 0%, #c7d2fe 100%); 
                        padding: 2rem; border-radius: 8px; text-align: center; margin: 2rem 0;'>
                <p style='margin: 0; color: #3730a3; font-size: 1.1rem; font-weight: 500;'>
                    👆 Selecione uma BDR na tabela acima para visualizar a análise técnica completa
                </p>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style='background: linear-gradient(135deg, #ffeaa7 0%, #fdcb6e 100%); 
                    padding: 2rem; border-radius: 8px; text-align: center;'>
            <h3 style='margin: 0; color: #7c3626;'>📊 Nenhuma oportunidade detectada</h3>
            <p style='margin: 0.5rem 0 0 0; color: #7c3626;'>
                Aguarde novas oportunidades ou ajuste os critérios de filtro
            </p>
        </div>
        """, unsafe_allow_html=True)

# Rodapé profissional
st.markdown("---")
st.markdown("""
<div style='text-align: center; padding: 2rem 0; color: #64748b;'>
    <p style='margin: 0; font-size: 0.9rem;'>
        <strong>Monitor BDR - Swing Trade Pro</strong> | Powered by Python, yFinance & Streamlit
    </p>
    <p style='margin: 0.5rem 0 0 0; font-size: 0.8rem;'>
        ⚠️ Este sistema é apenas para fins educacionais. Não constitui recomendação de investimento.
    </p>
</div>
""", unsafe_allow_html=True)
