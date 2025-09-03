import MetaTrader5 as mt5
from datetime import datetime
import time
import pytz
import os
import threading
from rich.live import Live
from rich.table import Table
from rich.console import Console

console = Console()

ROBO_NOME = "Robo Forex Fimathe"
ROBO_VERSAO = "09062025"
CAMINHO_CONFIG_GLOBAL = "config_global.txt"

# Cria config_global.txt se não existir
def verificar_ou_criar_config_global():
    if not os.path.exists(CAMINHO_CONFIG_GLOBAL):
        exemplo = "mt5_path=C:\\Program Files\\MetaTrader 5\\terminal64.exe\n"
        with open(CAMINHO_CONFIG_GLOBAL, "w") as f:
            f.write(exemplo)
        print(f"✅ Arquivo '{CAMINHO_CONFIG_GLOBAL}' criado com exemplo de caminho do MT5.")

# Lê o caminho do MT5
def carregar_config_global():
    if not os.path.exists(CAMINHO_CONFIG_GLOBAL):
        verificar_ou_criar_config_global()
    with open(CAMINHO_CONFIG_GLOBAL, "r") as f:
        for linha in f:
            if linha.startswith("mt5_path="):
                return linha.strip().split("=", 1)[1]
    return None

# Inicializa o MetaTrader 5 com o caminho configurado
verificar_ou_criar_config_global()
caminho_mt5 = carregar_config_global()
if not caminho_mt5 or not mt5.initialize(path=caminho_mt5):
    print("❌ Não foi possível iniciar o MetaTrader 5.")
    print(f"Verifique o caminho no arquivo '{CAMINHO_CONFIG_GLOBAL}'.")
    quit()

def verificar_ou_criar_arquivo_config(caminho_arquivo):
    if not os.path.exists(caminho_arquivo):
        exemplo = """ativo=EURUSD
volume=0.01
timeframe=M15
preco_compra=1.0850
preco_venda=1.0830
sl_compra=1.0820
tp_compra=1.0880
sl_venda=1.0860
tp_venda=1.0800

ativo=GBPUSD
volume=0.02
timeframe=M5
preco_compra=1.2650
preco_venda=1.2630
sl_compra=1.2620
tp_compra=1.2680
sl_venda=1.2660
tp_venda=1.2600
"""
        with open(caminho_arquivo, "w+") as f:
            f.write(exemplo)
        print(f"✅ Arquivo '{caminho_arquivo}' criado com configurações de exemplo.")

def converter_timeframe(valor):
    mapa = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15
    }
    return mapa.get(valor.upper(), mt5.TIMEFRAME_M15)

def carregar_config_ativos(caminho_arquivo):
    ativos = []
    with open(caminho_arquivo, "r") as f:
        linhas = f.readlines()

    bloco = {}
    for linha in linhas:
        linha = linha.strip()
        if not linha:
            if bloco:
                if 'timeframe' in bloco:
                    bloco['timeframe_mt5'] = converter_timeframe(bloco['timeframe'])
                else:
                    bloco['timeframe_mt5'] = mt5.TIMEFRAME_M15
                ativos.append(bloco)
                bloco = {}
            continue

        if "=" in linha:
            chave, valor = linha.split("=")
            chave = chave.strip()
            valor = valor.strip()
            if chave in ["volume", "preco_compra", "preco_venda", "sl_compra", "tp_compra", "sl_venda", "tp_venda"]:
                valor = float(valor)
            bloco[chave] = valor

    if bloco:
        if 'timeframe' in bloco:
            bloco['timeframe_mt5'] = converter_timeframe(bloco['timeframe'])
        else:
            bloco['timeframe_mt5'] = mt5.TIMEFRAME_M15
        ativos.append(bloco)

    return ativos

def salvar_log(ativo, mensagem):
    nome_arquivo = f"LOG_{ativo.upper()}.txt"
    with open(nome_arquivo, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now()}] {mensagem}\n")

def enviar_ordem(ativo, tipo_ordem, volume, preco, sl, tp):
    tipo = mt5.ORDER_TYPE_BUY if tipo_ordem == "buy" else mt5.ORDER_TYPE_SELL
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": ativo,
        "volume": volume,
        "type": tipo,
        "price": preco,
        "sl": sl,
        "tp": tp,
        "deviation": 10,
        "magic": 123456,
        "comment": "Robo AutoTrade",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
        salvar_log(ativo, f"✅ Ordem {tipo_ordem.upper()} enviada com sucesso: Preço {preco}, SL {sl}, TP {tp}")
        print(f"\n🟢 {ativo.upper()} - Ordem {tipo_ordem.upper()} executada com sucesso!")
        print(f"Entrada: {preco:.5f} | Stop Loss: {sl:.5f} | Take Profit: {tp:.5f}")
    else:
        salvar_log(ativo, f"❌ Falha ao enviar ordem {tipo_ordem.upper()}: {result}")
    return result

dados_ativos = {}
lock = threading.Lock()

def monitorar_ativo(config):
    ativo = config['ativo']
    timezone = pytz.timezone("Etc/UTC")
    ultimo_candle_time = None
    estado_ordem = "aguardando"
    ordens_executadas = 0
    operacao_finalizada = False

    while True:
        if operacao_finalizada:
            with lock:
                dados_ativos[ativo] = {"status": "Finalizado"}
            break

        timeframe = config.get('timeframe_mt5', mt5.TIMEFRAME_M15)
        rates = mt5.copy_rates_from_pos(ativo, timeframe, 0, 2)
        tick = mt5.symbol_info_tick(ativo)

        if rates is None or len(rates) < 2 or not tick:
            time.sleep(1)
            continue

        candle = rates[-2]
        hora_candle = datetime.fromtimestamp(candle['time'], timezone)
        fechamento = candle['close']
        abertura = candle['open']
        tamanho = abs(fechamento - abertura)
        pontos = tamanho * 100000

        preco_medio = abs(config['preco_compra'] - config['preco_venda']) * 100 / 2

        if estado_ordem == "aguardando" and tick.ask >= config['preco_compra']:
            estado_ordem = "Aguardando_Compra"
        elif estado_ordem == "aguardando" and tick.bid <= config['preco_venda']:
            estado_ordem = "aguardando_venda"

        with lock:
            dados_ativos[ativo] = {
                "bid": tick.bid,
                "ask": tick.ask,
                "ultimo": fechamento,
                "status": estado_ordem
            }

        if ultimo_candle_time != hora_candle:
            salvar_log(ativo, f"Candle fechado em {fechamento:.5f} | Tamanho: {pontos:.1f} pontos")
            ultimo_candle_time = hora_candle

            if estado_ordem == "compra_executada":
                if tick.bid <= config['sl_compra']:
                    salvar_log(ativo, f"🛑 Stop Loss da compra atingido em {tick.bid:.5f}")
                    if ordens_executadas ==1:
                        estado_ordem = "aguardando_venda"
                    else:
                        estado_ordem = 'Finalizado'


            elif estado_ordem == "venda_executada":
                if tick.ask >= config['sl_venda']:
                    salvar_log(ativo, f'🛑 Stop Loss da venda atingido em {tick.ask:.5f}')
                    if ordens_executadas == 1:
                        estado_ordem = 'Aguardando_Compra'
                    else:
                        estado_ordem = 'Finalizado'


            elif estado_ordem == "aguardando_venda":
                if fechamento < config['preco_venda'] and abs(fechamento - config['preco_venda']) < preco_medio:
                    resultado = enviar_ordem(ativo, "sell", config['volume'], tick.bid, config['sl_venda'], config['tp_venda'])
                    if resultado and resultado.retcode == mt5.TRADE_RETCODE_DONE:
                        estado_ordem = "venda_executada"
                        ordens_executadas += 1


            elif estado_ordem == "Aguardando_Compra":
                if fechamento > config['preco_compra'] and abs(fechamento - config['preco_compra']) < preco_medio:
                    resultado = enviar_ordem(ativo, "buy", config['volume'], tick.ask, config['sl_compra'], config['tp_compra'])
                    if resultado and resultado.retcode == mt5.TRADE_RETCODE_DONE:
                        estado_ordem = "compra_executada"
                        ordens_executadas += 1


            if estado_ordem == 'Finalizado' or ordens_executadas >= 2:
                salvar_log(ativo, '✔️ Duas ordens executadas. Encerrando ativo.')
                operacao_finalizada = True

        time.sleep(1)

def painel_precos():
    with Live(refresh_per_second=1) as live:
        while True:
            with lock:
                tabela = Table(title=f"{ROBO_NOME} - v{ROBO_VERSAO}")
                tabela.add_column("Ativo")
                tabela.add_column("Volume")
                tabela.add_column("Bid")
                tabela.add_column("Ask")
                tabela.add_column("Último Candle")
                tabela.add_column("Status")

                for config in ativos_config:
                    ativo = config["ativo"]
                    info = dados_ativos.get(ativo, {})
                    tabela.add_row(
                        ativo,
                        f"{config.get('volume', 0):.2f}", #Volume do config
                        f"{info.get('bid', 0):.5f}",
                        f"{info.get('ask', 0):.5f}",
                        f"{info.get('ultimo', 0):.5f}",
                        info.get('status', '-')
                    )


                live.update(tabela)
            time.sleep(1)

# Executa
caminho_config = "config_ativos.txt"
verificar_ou_criar_arquivo_config(caminho_config)
ativos_config = carregar_config_ativos(caminho_config)

console.print(f"\n🔍 Iniciando monitoramento dos ativos com {ROBO_NOME} (v{ROBO_VERSAO})...\n", style="bold green")

threading.Thread(target=painel_precos, daemon=True).start()

for config in ativos_config:
    threading.Thread(target=monitorar_ativo, args=(config,), daemon=True).start()

while True:
    time.sleep(1)
