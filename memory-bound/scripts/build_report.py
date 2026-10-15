"""Gera um relatório conciso de memory-bound nas seções do template da disciplina."""

import argparse
from io import BytesIO
import json
from pathlib import Path
from xml.sax.saxutils import escape

import reportlab
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak

from analyze_results import draw_curve, plt

PROJECT = Path(__file__).resolve().parents[1]


def number(value, digits=2):
    return 'não disponível' if value is None else f'{value:.{digits}f}'.replace('.', ',')


def mean_sd(group, metric, scale=1, digits=2):
    value, sd = group[metric + '_mean'], group[metric + '_sd']
    if value is None:
        return '-'
    return number(value * scale, digits) + (' ± ' + number(sd * scale, digits) if sd is not None else '')


def summary_figure(rows, groups):
    """Reapresenta os dados salvos com fontes legíveis no tamanho de impressão."""
    specs = [
        ('success_rps', 'Vazão de respostas válidas', 'Requisições/s', 1),
        ('mean_ms', 'Latência média dos sucessos', 'Segundos', 0.001),
        ('cpu_percent_of_limit', 'CPU do container', '% da quota de 6 CPUs', 1),
        ('memory_peak_mib', 'Pico de memória amostrado', 'MiB', 1),
    ]
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 8.5})
    fig, axes = plt.subplots(2, 2, figsize=(6.7, 4.55))
    for ax, (metric, title, ylabel, scale) in zip(axes.flat, specs):
        draw_curve(ax, rows, groups, metric, scale)
        ax.set_title(title, loc='left', fontsize=9.5, fontweight='bold', pad=7)
        ax.set_xlabel('Usuários simultâneos', fontsize=8.5)
        ax.set_ylabel(ylabel, fontsize=8.5)
        ax.set_xscale('log', base=2)
        ax.set_xticks([1, 2, 4, 8], labels=['1', '2', '4', '8'])
        ax.set_ylim(0, 105) if metric == 'cpu_percent_of_limit' else ax.set_ylim(bottom=0)
        ax.tick_params(labelsize=8)
        ax.grid(axis='y', alpha=0.2)
        ax.spines[['top', 'right']].set_visible(False)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper center', ncol=4, frameon=False, fontsize=9)
    fig.subplots_adjust(left=0.09, right=0.99, top=0.87, bottom=0.10, hspace=0.65, wspace=0.38)
    content = BytesIO()
    fig.savefig(content, format='png', dpi=220, facecolor='white')
    plt.close(fig)
    content.seek(0)
    return content


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis', type=Path, default=PROJECT / 'output/analysis')
    parser.add_argument('--pdf', type=Path, default=PROJECT / 'output/pdf/relatorio-memory-bound.pdf')
    parser.add_argument('--markdown', type=Path, default=PROJECT / 'docs/relatorio-memory-bound.md')
    args = parser.parse_args()
    audit = json.loads((args.analysis / 'audit.json').read_text())
    if not audit['complete_matrix'] or audit['issues'] or audit['observed_runs'] != 48:
        raise SystemExit('O relatório final exige 48 execuções e auditoria sem divergências')
    groups = json.loads((args.analysis / 'comparison.json').read_text())
    rows = json.loads((args.analysis / 'runs.json').read_text())
    provenance = json.loads((args.analysis / 'provenance.json').read_text())
    env = provenance['environment']
    manifest = env['dataset_manifest']
    host = provenance.get('host_observation')
    index = {(g['ram_mib'], g['users']): g for g in groups}
    font_directory = Path(reportlab.__file__).parent / 'fonts'
    for name, filename in [('ReportSans', 'Vera.ttf'), ('ReportSans-Bold', 'VeraBd.ttf')]:
        pdfmetrics.registerFont(TTFont(name, str(font_directory / filename)))
    styles = getSampleStyleSheet()
    for name, size, leading, before, after, font in [
        ('TitleCompact', 18, 23, 0, 8, 'ReportSans'),
        ('HeadingCompact', 12, 16, 10, 6, 'ReportSans-Bold'),
        ('BodyCompact', 9.5, 13, 0, 7, 'ReportSans'),
        ('SmallCompact', 8, 10.5, 0, 6, 'ReportSans'),
        ('CellCompact', 8, 10, 0, 0, 'ReportSans'),
    ]:
        styles.add(ParagraphStyle(name=name, fontName=font, fontSize=size, leading=leading,
                                  spaceBefore=before, spaceAfter=after))
    story, markdown = [], []

    def para(value, style='BodyCompact'):
        story.append(Paragraph(escape(value), styles[style]))
        markdown.append(value + '\n')

    def heading(value):
        para(value, 'HeadingCompact')
        markdown[-1] = '## ' + markdown[-1]

    def table(headers, data, widths):
        cell = lambda value: Paragraph(escape(str(value)), styles['CellCompact'])
        tab = Table([[cell(v) for v in headers], *[[cell(v) for v in row] for row in data]],
                    colWidths=[v * cm for v in widths], repeatRows=1, hAlign='LEFT')
        tab.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eeeeee')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LINEBELOW', (0, 0), (-1, -1), 0.25, colors.HexColor('#dddddd')),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.extend([tab, Spacer(1, 0.2 * cm)])
        markdown.append('| ' + ' | '.join(headers) + ' |\n|' + '|'.join(['---'] * len(headers)) + '|\n' +
                        '\n'.join('| ' + ' | '.join(str(v) for v in row) + ' |' for row in data) + '\n')

    para('Demanda, Provisionamento e Desempenho', 'TitleCompact')
    markdown[-1] = '# ' + markdown[-1]
    heading('Aplicações desenvolvidas')
    para('A ideia da aplicação é identificar cadastros duplicados em arquivos CSV e eliminar '
         'as ocorrências anteriores, mantendo a última encontrada de cada ID. Para fazer essa '
         'comparação, os registros únicos permanecem em memória durante o processamento. '
         'Assim, o envio simultâneo de arquivos aumenta a necessidade de RAM. O backend foi '
         'desenvolvido em Python 3.10 com FastAPI e retorna as contagens de registros e o tempo '
         'de processamento.')
    total_mib = sum(f['size_bytes'] for f in manifest['files']) / 2**20
    para(f'Foi usado o mesmo lote de quatro CSVs ({number(total_mib)} MiB), com '
         f'{manifest["expected"]["records_received"]} registros e '
         f'{manifest["expected"]["unique_records"]} IDs únicos, em todas as requisições.')
    heading('Configuração da VM e Deploy da Aplicação')
    host_description = (f'{host["cpu_brand"]}, {number(host["host_memory_bytes"] / 2**30, 0)} GiB de RAM'
                        if host else 'ARM64')
    para('Por dificuldades de preparar o ambiente com VirtualBox no computador disponível, '
         'os experimentos foram realizados localmente com Docker. Isso permitiu controlar RAM '
         'e CPU e repetir os testes com a mesma imagem da aplicação, construída pelo Dockerfile.')
    para(f'O hospedeiro foi um Mac ({host_description}). A VM Linux interna do Docker Desktop '
         f'dispunha de {number(env["docker_info"]["MemTotal"] / 2**30)} GiB e '
         f'{env["docker_info"]["NCPU"]} CPUs lógicas. Em cada container, aplicaram-se limites de '
         '500 MiB, 1 GiB, 2 GiB ou 4 GiB de RAM e quota fixa de seis CPUs, com swap desabilitado '
         'e seis workers. O Locust executou no hospedeiro, acessando a porta publicada da API.')
    heading('Teste de estresse da aplicação selecionada')
    para('O teste buscou observar o que acontece quando mais clientes usam a aplicação ao mesmo '
         'tempo e quando ela dispõe de menos memória. Para cada limite de RAM, simularam-se '
         '1, 2, 4 e 8 usuários simultâneos. Cada combinação foi repetida três vezes, '
         'totalizando 48 execuções.')
    para('Cada usuário virtual enviava o lote de CSVs, aguardava a resposta e iniciava outro '
         'envio. Cada execução começava com um container novo. Depois que todos os usuários '
         'estavam ativos, houve 10 segundos de aquecimento e, em seguida, 60 segundos de '
         'medição. CPU e memória foram registradas a cada meio segundo; entre execuções, '
         'aguardaram-se cinco segundos, alternando as configurações testadas.')
    para('A vazão mostra quantos envios foram concluídos corretamente por segundo, e a latência '
         'informa o tempo de resposta. O p95 é o tempo que pelo menos 95% das respostas válidas '
         'analisadas não ultrapassaram. Também se mediram o pico de memória e o uso de CPU '
         'em relação ao limite de seis CPUs.')
    para('Os tempos de resposta consideram apenas envios bem-sucedidos que começaram e '
         'terminaram durante a medição. Envios ainda em andamento ao final foram registrados '
         'separadamente. Falhas de atendimento e encerramentos por falta de memória (OOM) '
         'também foram registrados; os contadores OOM incluem o aquecimento.')
    para('Na tabela, os valores são médias das três repetições, inclusive o p95. O símbolo ± '
         'mostra o desvio padrão, que indica quanto os valores variaram entre as repetições.')
    para(f'Os 48 testes concluíram seus 60 segundos de medição. Em '
         f'{len(audit["incomplete_resource_windows"])} execuções faltaram amostras do monitor: '
         'essas coletas ficaram fora das médias de CPU/memória, mas os dados de requisições '
         'foram mantidos. Três repetições não estabelecem significância estatística.', 'SmallCompact')

    para('Comparação na maior demanda: oito usuários simultâneos.', 'SmallCompact')
    table(['RAM', 'Vazão req/s', 'Latência média s', 'p95 s', 'Falhas %', 'Testes com OOM'], [
        [label, mean_sd(index[(ram, 8)], 'success_rps'), mean_sd(index[(ram, 8)], 'mean_ms', 0.001),
         mean_sd(index[(ram, 8)], 'p95_ms', 0.001), mean_sd(index[(ram, 8)], 'failure_percent', digits=1),
         f'{index[(ram, 8)]["oom_runs"]}/3']
        for ram, label in [(500, '500 MiB'), (1024, '1 GiB'), (2048, '2 GiB'), (4096, '4 GiB')]
    ], [1.8, 3.0, 3.3, 3.0, 2.7, 3.2])

    story.append(PageBreak())
    heading('Resultados e interpretação')
    story.append(Image(summary_figure(rows, groups), width=17 * cm, height=17 * cm * 4.55 / 6.7))
    para('Figura 1. Médias ± desvio padrão; pontos claros mostram repetições. Cruzes indicam '
         'coletas de recursos com lacunas, excluídas das médias de CPU/memória.', 'SmallCompact')
    markdown.append('![Demanda, desempenho e recursos](../output/analysis/painel.png)\n')
    high, one = index[(4096, 8)], index[(4096, 1)]
    para('Com 500 MiB, houve OOM a partir de dois usuários; com 1 GiB, em oito. Em 2 e 4 GiB, '
         'não houve falhas ou OOM até oito usuários. Ampliar RAM evitou mortes por falta de memória '
         'nos níveis testados, mas não elevou a vazão em todas as combinações de demanda.')
    para(f'Em 4 GiB, passar de um para oito usuários elevou a vazão de '
         f'{number(one["success_rps_mean"])} para {number(high["success_rps_mean"])} req/s, '
         f'e a latência de {number(one["mean_ms_mean"] / 1000)} para '
         f'{number(high["mean_ms_mean"] / 1000)} s. O pico de memória passou de '
         f'{number(one["memory_peak_mib_mean"], 0)} para {number(high["memory_peak_mib_mean"], 0)} MiB; '
         f'a CPU média com oito usuários foi {number(high["cpu_percent_of_limit_mean"], 1)}% da quota.')
    para('Conclusão: maior demanda aumentou a latência e o consumo de recursos; RAM insuficiente '
         'causou falhas e queda da vazão válida. Os resultados valem para este hardware e dataset; '
         'parsing, GIL, upload e arquivos temporários também influenciam o desempenho. Latências '
         'consideram somente sucessos completos e devem ser lidas junto de falhas e pendentes.')
    para('Dados completos: results/' + Path(audit['input']).name + '. Tabelas por cenário: '
         'output/analysis/comparison.csv.', 'SmallCompact')

    heading('Por que usar seis CPUs e seis workers?')
    para('Antes dos testes de RAM, foram comparadas duas configurações de CPU/workers, '
         'ambas com 4 GiB, oito usuários e três cargas de 30 segundos. Essa calibração '
         'orientou a escolha dos recursos que permaneceriam fixos nos 48 experimentos.')
    table(['Configuração', 'Vazão média ± desvio padrão (req/s)', 'CPU média (% da quota)'], [
        ['4 CPUs / 4 workers', '1,62 ± 0,14', '75,44'],
        ['6 CPUs / 6 workers', '1,36 ± 0,12', '52,63'],
    ], [5.0, 7.0, 5.0])
    para('Optou-se por seis CPUs e seis workers para ampliar a margem em relação à quota '
         'global de CPU. A comparação não demonstrou ganho de vazão: CPU e workers variaram '
         'juntos e as configurações foram executadas em sequência. Portanto, não se conclui '
         'que seis CPUs causem pior desempenho nem que a RAM seja o único gargalo. '
         'Os resultados da calibração foram analisados separadamente dos experimentos finais.', 'SmallCompact')

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont('ReportSans', 8)
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, str(doc.page))
        canvas.restoreState()

    args.pdf.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(str(args.pdf), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                                 topMargin=1.6 * cm, bottomMargin=1.6 * cm,
                                 title='Memory-bound: Demanda, Provisionamento e Desempenho',
                                 author='Victor Vili Xavier Luna')
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text('\n'.join(markdown))
    print(f'Relatório: {args.pdf}\nFonte editável: {args.markdown}')


if __name__ == '__main__':
    main()
