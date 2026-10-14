"""Gera o relatório memory-bound nas seções do template da disciplina."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

import reportlab
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                               Image, PageBreak, Preformatted, KeepTogether)

PROJECT = Path(__file__).resolve().parents[1]


def number(value, digits=2):
    return 'não disponível' if value is None else f'{value:.{digits}f}'.replace('.', ',')


def mean_sd(group, metric, scale=1, digits=2):
    value, sd = group[metric + '_mean'], group[metric + '_sd']
    if value is None:
        return '-'
    return number(value * scale, digits) + (' ± ' + number(sd * scale, digits) if sd is not None else '')


def paragraphs(groups, rows, audit):
    index = {(g['ram_mib'], g['users']): g for g in groups}
    low, high = index[(500, 8)], index[(4096, 8)]
    one = index[(4096, 1)]
    oom_runs = sum(g['oom_runs'] for g in groups)
    fail_runs = sum(bool(r.get('failures')) for r in rows)
    conclusion = (
        f'Nas 48 execuções, {fail_runs} tiveram falhas HTTP na janela e {oom_runs} apresentaram '
        f'evidência de morte por falta de memória no ponto. Com oito usuários, a vazão válida média '
        f'foi {number(low["success_rps_mean"])} req/s em 500 MiB e '
        f'{number(high["success_rps_mean"])} req/s em 4 GiB. '
        'Os resultados permitem comparar capacidade de atendimento e pressão de memória, '
        'sem atribuir todo o custo da aplicação exclusivamente à RAM.'
    )
    demand = (
        f'Em 4 GiB, aumentar a demanda de um para oito usuários alterou a vazão média de '
        f'{number(one["success_rps_mean"])} para {number(high["success_rps_mean"])} req/s '
        f'e a latência média das respostas válidas de {number(one["mean_ms_mean"], 0)} para '
        f'{number(high["mean_ms_mean"], 0)} ms. A memória máxima amostrada média passou de '
        f'{number(one["memory_peak_mib_mean"], 1)} para {number(high["memory_peak_mib_mean"], 1)} MiB. '
        'Mais usuários representam mais requisições simultâneas em um modelo fechado, '
        'não uma taxa fixa de chegada.'
    )
    provisioning = (
        f'Na demanda de oito usuários, a proporção média de falhas foi '
        f'{number(low["failure_percent_mean"], 1)}% com 500 MiB e '
        f'{number(high["failure_percent_mean"], 1)}% com 4 GiB. '
        'Ler esses percentuais junto da vazão válida e dos eventos OOM evita interpretar '
        'respostas rápidas de erro como bom desempenho. Os eventos de OOM abrangem '
        'aquecimento e medição; o total do ponto não é automaticamente um total só da janela.'
    )
    comparison = []
    thresholds = []
    for ram in (500, 1024, 2048, 4096):
        group = index[(ram, 8)]
        comparison.append(f'{ram} MiB: {mean_sd(group, "success_rps")} req/s, '
                          f'{mean_sd(group, "mean_ms", 0.001)} s e {group["oom_runs"]}/3 pontos com OOM')
        observed = [g['users'] for g in groups if g['ram_mib'] == ram and g['oom_runs']]
        thresholds.append(f'{ram} MiB: primeiro nível com OOM em {min(observed)} usuários' if observed
                          else f'{ram} MiB: OOM não observado até oito usuários')
    coverage = (
        f'A auditoria conferiu {audit["checks"]} condições e não encontrou divergências entre '
        'limites reais, registros individuais e métricas derivadas. '
        f'{audit["statuses"].get("resource_failure_before_window", 0)} pontos não produziram janela comparável. '
        f'{len(audit["incomplete_resource_windows"])} execuções tiveram cobertura de recursos '
        'incompleta. Essas amostras são preservadas, mas não entram nas médias comparativas '
        'de CPU/memória; as tabelas informam o número de observações disponíveis.'
    )
    return {'conclusion': conclusion, 'demand': demand, 'provisioning': provisioning,
            'comparison': comparison, 'coverage': coverage, 'thresholds': '; '.join(thresholds) + '.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis', type=Path, default=PROJECT / 'output/analysis')
    parser.add_argument('--pdf', type=Path, default=PROJECT / 'output/pdf/relatorio-memory-bound.pdf')
    parser.add_argument('--markdown', type=Path, default=PROJECT / 'docs/relatorio-memory-bound.md')
    parser.add_argument('--student-id', default='122110387', help='Matrícula informada pelo autor')
    args = parser.parse_args()
    audit = json.loads((args.analysis / 'audit.json').read_text())
    if not audit['complete_matrix'] or audit['issues'] or audit['observed_runs'] != 48:
        raise SystemExit('O relatório final exige matriz completa e auditoria sem divergências')
    groups = json.loads((args.analysis / 'comparison.json').read_text())
    rows = json.loads((args.analysis / 'runs.json').read_text())
    provenance = json.loads((args.analysis / 'provenance.json').read_text())
    env = provenance['environment']
    host_observation = provenance.get('host_observation')
    text = paragraphs(groups, rows, audit)
    args.pdf.parent.mkdir(parents=True, exist_ok=True)
    # Embed the bundled fonts so PDF viewers do not depend on local substitutes.
    font_directory = Path(reportlab.__file__).parent / 'fonts'
    pdfmetrics.registerFont(TTFont('ReportSans', str(font_directory / 'Vera.ttf')))
    pdfmetrics.registerFont(TTFont('ReportSans-Bold', str(font_directory / 'VeraBd.ttf')))
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='ReportTitle', fontName='ReportSans', fontSize=20, leading=25, spaceAfter=12))
    styles.add(ParagraphStyle(name='ReportHeading', fontName='ReportSans', fontSize=15, leading=19, spaceBefore=14, spaceAfter=9))
    styles.add(ParagraphStyle(name='ReportSubheading', fontName='ReportSans-Bold', fontSize=11, leading=15, spaceBefore=10, spaceAfter=6))
    styles.add(ParagraphStyle(name='ReportBody', fontName='ReportSans', fontSize=9, leading=13, alignment=TA_LEFT, spaceAfter=8))
    styles.add(ParagraphStyle(name='ReportSmall', fontName='ReportSans', fontSize=8, leading=10.5, spaceAfter=7))
    styles.add(ParagraphStyle(name='ReportCell', fontName='ReportSans', fontSize=7.5, leading=9.5))
    styles.add(ParagraphStyle(name='ReportCode', fontName='Courier', fontSize=8, leading=11, spaceAfter=8))
    story = []
    markdown = []

    def title(value):
        story.append(Paragraph(escape(value), styles['ReportTitle']))
        markdown.append('# ' + value + '\n')

    def heading(value, level=2):
        style = styles['ReportHeading'] if level == 2 else styles['ReportSubheading']
        story.append(Paragraph(escape(value), style))
        markdown.append('#' * level + ' ' + value + '\n')

    def para(value, small=False):
        story.append(Paragraph(escape(value), styles['ReportSmall' if small else 'ReportBody']))
        markdown.append(value + '\n')

    def table(headers, data, widths):
        cell = lambda value: Paragraph(escape(str(value)), styles['ReportCell'])
        t = Table([[cell(h) for h in headers], *[[cell(v) for v in row] for row in data]], colWidths=widths, repeatRows=1, hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eeeeee')),
                               ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                               ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.HexColor('#777777')),
                               ('LINEBELOW', (0, 1), (-1, -1), 0.25, colors.HexColor('#dddddd')),
                               ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5),
                               ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5)]))
        story.extend([t, Spacer(1, 0.2 * cm)])
        markdown.append('| ' + ' | '.join(headers) + ' |\n|' + '|'.join(['---'] * len(headers)) + '|\n' +
                        '\n'.join('| ' + ' | '.join(str(v) for v in row) + ' |' for row in data) + '\n')

    def figure(name, caption):
        picture = Image(str(args.analysis / f'{name}.png'))
        picture.drawHeight = 17 * cm * picture.imageHeight / picture.imageWidth
        picture.drawWidth = 17 * cm
        story.append(KeepTogether([picture,
                                    Paragraph(escape(caption), styles['ReportSmall']), Spacer(1, 0.2 * cm)]))
        markdown.append(f'![{caption}](../output/analysis/{name}.png)\n')

    title('Demanda, Provisionamento e Desempenho')
    collected = datetime.fromtimestamp(min(row['start_epoch'] for row in rows if row.get('complete')), timezone.utc).astimezone(ZoneInfo('America/Fortaleza'))
    months = ('janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro')
    para(f'Aplicação memory-bound | Experimentos locais em Docker | {collected.day} de {months[collected.month - 1]} de {collected.year}')
    last_window = datetime.fromtimestamp(max(row['end_epoch'] for row in rows if row.get('complete')), timezone.utc).astimezone(ZoneInfo('America/Fortaleza'))
    para(f'Janelas observadas entre {collected:%H:%M} e {last_window:%H:%M}, horário de Fortaleza (UTC-3). '
         f'Tempo útil de medição: {sum(row.get("duration_seconds", 0) for row in rows if row.get("complete"))/60:.0f} minutos.', small=True)
    para('Grupo 15. Parte memory-bound: Victor Vili Xavier Luna. Matrícula: ' + (args.student_id or 'a informar') + '.', small=True)
    para(text['conclusion'])
    heading('Aplicações desenvolvidas')
    heading('Aplicação memory-bound', 3)
    para('Desenvolvemos um backend Python 3.10 com FastAPI para consolidar cadastros enviados em arquivos CSV. '
         'A rota POST /memory-test recebe vários arquivos em ordem, lê os registros incrementalmente e mantém '
         'um dicionário com o registro completo de cada ID. A última ocorrência substitui a anterior. '
         'A resposta contém apenas contagens e tempo interno de processamento; o cadastro consolidado não é devolvido.')
    para('A necessidade de manter os registros únicos até o final produz pressão de capacidade de memória. '
         'Entretanto, parsing de texto, construção de objetos Python, GIL, upload e arquivos temporários também '
         'consomem recursos. O endpoint síncrono é executado em threads; seis processos Uvicorn permitem '
         'paralelismo entre processos. Cada usuário virtual envia uma requisição por vez, sem espera artificial.')
    manifest = env['dataset_manifest']
    expected = manifest['expected']
    # O manifesto também fica preservado junto aos resultados para conferir todos os hashes.
    table(['Dataset', 'Arquivos', 'Registros', 'IDs únicos', 'Substituições'],
          [['Grande', len(manifest['files']), expected['records_received'], expected['unique_records'], expected['replaced_occurrences']]],
          [3.2*cm, 2.0*cm, 3.7*cm, 3.5*cm, 4.6*cm])
    total_mib = sum(item['size_bytes'] for item in manifest['files']) / 2**20
    para(f'O lote possui {number(total_mib)} MiB; cada descrição tem {manifest["parameters"]["description_bytes"]} bytes. '
         'Os mesmos quatro arquivos e a mesma ordem são usados em todas as requisições; o manifesto '
         'registra tamanhos e hashes SHA-256. O volume de arquivos não equivale diretamente à memória '
         'residente dos objetos Python ou ao consumo total do cgroup.')
    heading('Monitoramento da aplicação e da infraestrutura', 3)
    para('Locust no macOS registra respostas válidas, falhas e latências HTTP. Um monitor dentro do container '
         'acompanha o processo mestre Uvicorn e seus descendentes, com psutil e cgroup v2. A cada 0,5 segundo '
         'coleta CPU, RSS, memory.current, limite de RAM, swap e contadores OOM. Outro monitor acompanha '
         'a árvore de processos do gerador no Mac. RSS pode duplicar páginas compartilhadas; memory.current '
         'inclui também cache contabilizado ao container.')

    story.append(PageBreak())
    heading('Configuração da VM e Deploy da Aplicação')
    para('Estas coletas utilizaram containers Docker no Mac ARM64, apoiados na VM Linux interna do Docker Desktop. '
         'Os limites de provisionamento foram aplicados ao container por cgroup, e não como RAM/vCPUs '
         'de uma VM VirtualBox. Portanto, este relatório descreve experimentos locais Docker; não relata '
         'deploy nem medições realizadas no VDI do professor ou no LCC.')
    info = env['docker_info']
    table(['Componente', 'Configuração registrada'], [
        ['Hospedeiro', ('macOS ARM64; ' + host_observation['cpu_brand'] + '; ' + number(host_observation['host_memory_bytes']/2**30, 0) + ' GiB de RAM; Locust fora do container') if host_observation else 'macOS ARM64; Locust fora do container'],
        ['VM interna Docker Desktop', f"{info['Architecture']}; {info['NCPU']} CPUs lógicas; {info['MemTotal']/2**30:.2f} GiB de RAM".replace('.', ',')],
        ['Container', 'Linux ARM64; Python 3.10; 6 CPUs de quota; 6 workers Uvicorn'],
        ['Memória e swap', '500 / 1024 / 2048 / 4096 MiB; swap desabilitado'],
        ['Rede', 'Porta dinâmica do hospedeiro 127.0.0.1 para porta 8000 do container'],
        ['Imagem', env['image']['Id'][:35] + '...'],
    ], [5.0*cm, 12.0*cm])
    para('O Dockerfile instala as dependências da API e psutil, copia os fontes e disponibiliza a porta 8000. '
         'O executor cria um container novo para cada ponto, monta seu diretório de resultados, inicia seis '
         'workers, valida a API com um CSV mínimo e registra as dependências reais. Os datasets ficam no '
         'hospedeiro; são enviados por multipart em fluxo e conferidos por manifesto e SHA-256.')
    code = ('docker build -t memory-bound:experiment memory-bound\n'
            'memory-bound/.venv/bin/python memory-bound/scripts/docker_experiment.py')
    story.append(Preformatted(code, styles['ReportCode']))
    markdown.append('```bash\n' + code + '\n```\n')
    para('O código e protocolo utilizados foram preservados em snapshot, junto de ID da imagem, versão '
         'Docker, estado Git, manifesto, configurações efetivas e logs. Ao final de cada ponto, o executor '
         'encerra monitores e remove apenas o container que criou. A identificação completa da imagem '
         'e os detalhes de CPU/RAM estão em environment.json e container.json.')

    heading('Teste de Stress da Aplicação selecionada')
    heading('Escolha de CPU e workers', 3)
    para('Antes dos testes de RAM, foram comparadas configurações de 4 CPUs/4 workers e '
         '6 CPUs/6 workers, com 4 GiB, oito usuários, o mesmo dataset e três execuções de '
         '30 segundos por configuração. A vazão média foi 1,62 e 1,36 req/s, respectivamente, '
         'sem demonstrar ganho ao ampliar CPU/workers. Adotaram-se 6 CPUs/6 workers para '
         'ampliar a margem em relação à quota global de CPU, mantendo-os constantes nos '
         '48 experimentos. A calibração teve duração e metodologia próprias; seus resultados '
         'não foram misturados aos testes finais. A escolha não garante gargalo exclusivo '
         'de memória nem permite concluir que seis CPUs causem pior desempenho.')
    table(['Cenário', 'RAM', 'CPU', 'Workers', 'Demandas', 'Repetições'], [
        [f'C{i+1}', f'{ram} MiB', '6', '6', '1, 2, 4, 8', '3 por demanda']
        for i, ram in enumerate((500, 1024, 2048, 4096))
    ], [1.6*cm, 2.7*cm, 1.6*cm, 2.0*cm, 4.0*cm, 5.1*cm])
    para('A matriz possui 4 configurações de RAM × 4 demandas × 3 repetições, totalizando 48 execuções. '
         'Cada ponto tem rampa de N usuários a N usuários/s, aquecimento de 10 segundos após todos '
         'estarem ativos e janela de medição de 60 segundos. Há 5 segundos entre containers. A ordem '
         'rotaciona demanda e RAM e inverte RAM na segunda rodada para reduzir efeitos da ordem. '
         'Aquecimento não garante estado estacionário; o histórico temporal permanece disponível.')

    story.append(PageBreak())
    heading('Metodologia de comparação', 3)
    para('Vazão válida é o número de respostas corretas concluídas dentro da janela dividido por 60 segundos. '
         'Conclusões de requisições iniciadas no aquecimento contribuem para vazão, mas não para latência. '
         'Latência média e p95 principais incluem somente sucessos iniciados e concluídos na janela. '
         'Falhas são apresentadas separadamente; sem sucesso, a latência é indisponível, não zero.')
    para('Requisições iniciadas na janela e ainda pendentes no final são censuradas e contadas explicitamente. '
         'Elas não são classificadas artificialmente como falha ou sucesso. Médias e p95 podem favorecer '
         'respostas curtas quando há censura, por isso devem ser lidos junto de pendentes e vazão. '
         'O p95 usa nearest rank. Os CSVs acumulados do Locust incluem aquecimento; a comparação usa '
         'load/measurement.json e os registros individuais de requests.csv.')
    para('No modelo fechado sem espera, é esperado haver requisições pendentes em qualquer instante. '
         'Seu número isolado não demonstra falha nem saturação; ele informa a censura da amostra.')
    para('Cada ponto é uma observação independente para agregação. As tabelas e gráficos mostram média '
         'e desvio padrão amostral entre as três repetições; p95 é a média dos p95 de cada repetição, '
         'não um percentil de todas as requisições misturadas. Três repetições não estabelecem '
         'significância estatística nem intervalos de confiança confiáveis.')
    para(text['coverage'])
    heading('Resultados comparativos de desempenho', 3)
    table(['RAM MiB', 'Usuários', 'n HTTP/lat', 'Vazão válida req/s', 'Latência média s', 'p95 s', 'Falhas %'], [
        [g['ram_mib'], g['users'], f"{g['complete_windows']}/{g['mean_ms_n']}", mean_sd(g, 'success_rps'),
         mean_sd(g, 'mean_ms', 0.001), mean_sd(g, 'p95_ms', 0.001), mean_sd(g, 'failure_percent', digits=1)] for g in groups
    ], [1.7*cm, 1.6*cm, 1.9*cm, 3.1*cm, 3.1*cm, 2.8*cm, 2.8*cm])
    para('Valores = média ± desvio padrão entre repetições. n HTTP/lat = janelas completas / '
         'repetições com latência de sucesso disponível. Traço indica ausência de observação.', small=True)

    story.append(PageBreak())
    heading('Demanda e desempenho', 3)
    figure('vazao', 'Figura 1. Vazão válida por demanda e provisionamento. Pontos claros mostram cada repetição.')
    figure('latencia', 'Figura 2. Latência média dos sucessos inteiramente contidos na janela; ler junto de pendentes e falhas.')
    para(text['demand'])

    story.append(PageBreak())
    heading('Utilização dos recursos', 3)
    figure('cpu', 'Figura 3. CPU normalizada pela quota de seis CPUs. Cruzes indicam coletas com lacunas, fora das médias.')
    figure('memoria', 'Figura 4. Pico amostrado do cgroup. Cruzes indicam coletas parciais; picos podem ter sido perdidos nas lacunas.')
    para('CPU é calculada pela diferença do contador cumulativo entre amostras dentro da janela, '
         'dividida pelo intervalo real e pela quota. O pico de memória é amostrado e pode perder picos '
         'entre leituras. Métricas de sistema do psutil refletem a VM interna Docker, não o limite '
         'de RAM do container.')

    story.append(PageBreak())
    heading('Falhas e falta de memória', 3)
    figure('falhas', 'Figura 5. Percentual de falhas entre respostas concluídas na janela.')
    figure('oom', 'Figura 6. Eventos OOM kill contabilizados no ponto inteiro, incluindo aquecimento.')
    para(text['provisioning'])

    story.append(PageBreak())
    heading('Requisições pendentes e interpretação', 3)
    figure('pendentes', 'Figura 7. Requisições ainda em andamento no fim da janela. Não equivalem a falhas.')
    for item in text['comparison']:
        para(item, small=True)
    para(text['thresholds'] + ' Esses são os primeiros níveis observados na grade testada, não limiares universais.', small=True)
    para('O efeito de provisionamento deve ser avaliado para a mesma demanda. OOM indica pressão de '
         'capacidade real. Por outro lado, ampliar RAM além do conjunto necessário não garante aumento '
         'da vazão: parsing, upload, armazenamento temporário, GIL e distribuição das conexões '
         'entre workers continuam participando do tempo total.')
    heading('Conclusões', 3)
    para(text['conclusion'])
    para('As conclusões valem para este backend, dataset, hospedeiro e modelo fechado de carga. '
         'Não se mediram temperatura, frequência, pressão global de memória do macOS ou desempenho '
         'físico do armazenamento. O computador não foi reservado exclusivamente ao experimento. '
         'Não extrapolar os limiares observados para outro hardware nem afirmar gargalo exclusivamente '
         'de RAM. A etapa VirtualBox/LCC, se mantida na avaliação, exige medição própria.')

    story.append(PageBreak())
    heading('Detalhamento de recursos e rastreabilidade', 3)
    table(['RAM MiB', 'Usuários', 'n recursos', 'CPU % quota', 'Pico RAM MiB', 'Pontos OOM/3', 'Pendentes'], [
        [g['ram_mib'], g['users'], g['covered_resource_windows'], mean_sd(g, 'cpu_percent_of_limit', digits=1),
         mean_sd(g, 'memory_peak_mib', digits=1), f"{g['oom_runs']}/3", mean_sd(g, 'in_flight_at_end', digits=1)] for g in groups
    ], [1.7*cm, 1.6*cm, 1.9*cm, 3.1*cm, 3.6*cm, 2.5*cm, 2.6*cm])
    para('n recursos conta janelas com cobertura adequada. Contadores finais OOM abrangem todo o '
         'ponto; quando o container encerra antes da leitura, o estado OOMKilled permanece evidência, '
         'mas a quantidade de mortes pode ficar indisponível. Não preencher ausência com zero.', small=True)
    input_path = Path(audit['input'])
    para('Diretório dos dados brutos: ' + input_path.name + '.', small=True)
    para('Arquivos derivados: output/analysis/runs.csv, comparison.csv, audit.json e gráficos PNG/SVG. '
         'Cada ponto preserva configuração, validation.json, measurement.json, requests.csv, CSVs dos '
         'monitores, logs, dependências e docker inspect. O relatório é reproduzido pelos scripts '
         'analyze_results.py e build_report.py.', small=True)
    para('Os dados brutos ficam ignorados pelo Git durante a coleta. O snapshot e o manifesto permitem '
         'conferir exatamente o código e os CSVs usados; incluir os artefatos selecionados na entrega '
         'do grupo. O template fornecido orientou as três seções principais; esta parte cobre apenas '
         'memory-bound.', small=True)
    footer = lambda canvas, doc: (canvas.saveState(), canvas.setFont('ReportSans', 8),
                                   canvas.drawRightString(A4[0] - 2*cm, 1.2*cm, str(doc.page)), canvas.restoreState())
    document = SimpleDocTemplate(str(args.pdf), pagesize=A4, rightMargin=2*cm, leftMargin=2*cm,
                                 topMargin=1.8*cm, bottomMargin=1.8*cm, title='Demanda Provisionamento e Desempenho Memory-bound',
                                 author='Victor Vili Xavier Luna')
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text('\n'.join(markdown))
    print(f'Relatório: {args.pdf}\nFonte editável: {args.markdown}')


if __name__ == '__main__':
    main()
