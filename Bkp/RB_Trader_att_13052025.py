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

# Verifica e cria config_ativos.txt se não existir
def verificar_ou_criar_arquivo_config(caminho_arquivo):
    if not os.path.exists(caminho_arquivo):
        exemplo = """ativo=EURUSD
volume=0.01
preco_compra=1.0850
preco_venda=1.0830
sl_compra=1.0820
tp_compra=1.0880
sl_venda=1.0860
tp_venda=1.0800

ativo=GBPUSD
volume=0.02
preco_compra=1.2650
preco_venda=1.2630
sl_compra=1.2620
tp_compra=1.2680
sl_venda=1.2660
tp_venda=1.2600
"""
        with open(caminho_arquivo, "w") as f:
            f.write(exemplo)
        print(f"✅ Arquivo '{caminho_arquivo}' criado com configurações de exemplo.")

# Carrega as configurações dos ativos do arquivo txt
def carregar_config_ativos(caminho_arquivo):
    ativos = []
    with open(caminho_arquivo, "r") as f:
        linhas = f.readlines()

    bloco = {}
    for linha in linhas:
        linha = linha.strip()
        if not linha:
            if bloco:
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
        ativos.append(bloco)

    return ativos

# Inicializa o MetaTrader 5
if not mt5.initialize():
    print("❌ Não foi possível iniciar o MetaTrader 5")
    quit()

# Função para salvar log em arquivo
def salvar_log(ativo, mensagem):
    nome_arquivo = f"LOG_{ativo.upper()}.txt"
    with open(nome_arquivo, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now()}] {mensagem}\n")

# Enviar ordem de compra ou venda
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

# Dicionário para manter os dados atualizados
dados_ativos = {}
lock = threading.Lock()

# Monitora cada ativo
def monitorar_ativo(config):
    ativo = config['ativo']
    timezone = pytz.timezone("Etc/UTC")
    ultimo_candle_time = None
    estado_ordem = "aguardando"
    operacao_finalizada = False

    while True:
        if operacao_finalizada:
            with lock:
                dados_ativos[ativo] = {"status": "Finalizado"}
            break

        rates = mt5.copy_rates_from_pos(ativo, mt5.TIMEFRAME_M15, 0, 2)
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

        preco_medio = abs(config['preco_compra'] - config['preco_venda']) * 100 / 2  # Modificação aqui

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
                    estado_ordem = "aguardando_venda"

            elif estado_ordem == "aguardando_venda":
                if fechamento < config['preco_venda'] and abs(fechamento - config['preco_venda']) < preco_medio:
                    resultado = enviar_ordem(ativo, "sell", config['volume'], tick.bid, config['sl_venda'], config['tp_venda'])
                    if resultado and resultado.retcode == mt5.TRADE_RETCODE_DONE:
                        estado_ordem = "venda_executada"

            elif estado_ordem == "venda_executada":
                salvar_log(ativo, "🎯 Venda realizada após stop da compra. Encerrando ativo.")
                operacao_finalizada = True

            elif estado_ordem == "aguardando_compra" or estado_ordem == "aguardando":
                if fechamento > config['preco_compra'] and abs(fechamento - config['preco_compra']) < preco_medio:
                    resultado = enviar_ordem(ativo, "buy", config['volume'], tick.ask, config['sl_compra'], config['tp_compra'])
                    if resultado and resultado.retcode == mt5.TRADE_RETCODE_DONE:
                        estado_ordem = "compra_executada"

        time.sleep(1)

# Exibe a tabela ao vivo
def painel_precos():
    with Live(refresh_per_second=1) as live:
        while True:
            with lock:
                tabela = Table(title="Monitoramento de Ativos")
                tabela.add_column("Ativo")
                tabela.add_column("Bid")
                tabela.add_column("Ask")
                tabela.add_column("Último Candle")
                tabela.add_column("Status")

                for ativo, info in dados_ativos.items():
                    tabela.add_row(
                        ativo,
                        f"{info.get('bid', 0):.5f}",
                        f"{info.get('ask', 0):.5f}",
                        f"{info.get('ultimo', 0):.5f}",
                        info.get('status', "-")
                    )

                live.update(tabela)
            time.sleep(1)

# Executa
caminho_config = "config_ativos.txt"
verificar_ou_criar_arquivo_config(caminho_config)
ativos_config = carregar_config_ativos(caminho_config)

console.print("\n🔍 Iniciando monitoramento dos ativos...\n", style="bold green")

threading.Thread(target=painel_precos, daemon=True).start()

for config in ativos_config:
    threading.Thread(target=monitorar_ativo, args=(config,), daemon=True).start()

while True:
    time.sleep(1)
