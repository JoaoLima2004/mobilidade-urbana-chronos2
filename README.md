# mobilidade-urbana-chronos2
Experimentos de previsão de congestionamento viário em São Paulo utilizando o modelo Chronos-2, com dados da CET, comparação com métodos de referência e avaliação por métricas de erro. Projeto acadêmico de Engenharia da Computação voltado à análise de mobilidade urbana e à identificação de pontos críticos.

# Previsão de lentidão viária em São Paulo com Chronos-2

Repositório acadêmico do projeto de Engenharia da Computação sobre análise e previsão de lentidão viária em São Paulo. O foco deste repositório é documentar o experimento retrospectivo com o modelo Chronos-2 e compará-lo com métodos de referência simples.

**Repositório:** https://github.com/JoaoLima2004/mobilidade-urbana-chronos2  
**Modelo:** [`amazon/chronos-2`](https://huggingface.co/amazon/chronos-2)  
**Artigo relacionado:** estudo de previsão horária de lentidão viária com dados públicos da CET.

## Escopo do experimento

- Fonte dos registros de lentidão: dados públicos associados à Companhia de Engenharia de Tráfego (CET) de São Paulo.
- Período histórico informado no manifesto: 3 de janeiro de 2022 a 15 de dezembro de 2023.
- Base de entrada para o experimento: `dados/tratado/series_horarias.csv`.
- Séries horárias avaliadas: 35 séries por corredor/sentido.
- Avaliação: 14 janelas retrospectivas, com horizonte de previsão de 24 horas e avanço de 24 horas entre origens de previsão.
- Modelo principal: Chronos-2, sem ajuste fino (*zero-shot*), executado em CPU.
- Variável prevista: extensão de lentidão/congestionamento, em quilômetros, por série e hora.

Este repositório documenta um experimento retrospectivo. **Não representa um sistema operacional de previsão em tempo real nem uma validação completa de todas as funcionalidades previstas para o produto acadêmico.**

## Métodos comparados

1. **Ingênuo simples:** repete o último valor observado.
2. **Ingênuo sazonal diário:** repete o padrão observado 24 horas antes (`m = 24`).
3. **Ingênuo sazonal semanal:** repete o padrão observado 168 horas antes (`m = 168`).
4. **Chronos-2:** modelo pré-treinado `amazon/chronos-2`, usado sem ajuste fino.

As métricas principais são o erro absoluto médio (MAE, em quilômetros) e o erro absoluto escalado médio (MASE). Os resultados são calculados nas janelas e séries descritas nos manifestos de execução.

## Resultados registrados

Resultados agregados da avaliação principal:

| Método | MAE médio (km) | MASE médio |
|---|---:|---:|
| Chronos-2 | **0,3008** | **0,9608** |
| Ingênuo sazonal semanal (`m = 168`) | 0,3864 | 1,1168 |
| Ingênuo sazonal diário (`m = 24`) | 0,4251 | 1,3351 |
| Ingênuo simples | 0,4842 | 1,5192 |

Nessa avaliação, o Chronos-2 apresentou o menor MAE médio e venceu o baseline sazonal diário em 31 de 35 séries e o semanal em 28 de 35. O desempenho, contudo, varia entre séries: a mediana do MAE e resultados individuais também devem ser considerados, não apenas a média agregada.

### Análise de robustez

Uma análise adicional excluiu as três séries sem valores positivos observados durante o período de teste, restando 32 séries. Os resultados médios registrados foram:

| Método | MAE médio (km) | MASE médio |
|---|---:|---:|
| Chronos-2 | **0,3289** | 1,0505 |
| Ingênuo sazonal semanal (`m = 168`) | 0,4225 | 1,2198 |
| Ingênuo sazonal diário (`m = 24`) | 0,4650 | 1,4602 |
| Ingênuo simples | 0,5296 | 1,6617 |

A análise de robustez preserva a vantagem do Chronos-2 em MAE médio. O MASE médio do Chronos-2 nessa análise é superior a 1; portanto, esse resultado não deve ser descrito como superior a todos os baselines segundo todas as métricas.

Os valores acima refletem os arquivos de resultados disponibilizados para o projeto. Para avaliação científica, consulte também os dados por janela, por série, as previsões e os manifestos de execução; não use apenas a tabela agregada.

## Ambiente registrado

O manifesto da execução principal informa as seguintes versões:

- Python 3.12.10
- pandas 3.1.0
- NumPy 2.5.4
- `chronos-forecasting` 2.3.2
- PyTorch 2.14.1+cpu
- Matplotlib 3.11.2
- Dispositivo: CPU
- Semente configurada: 42

As versões acima descrevem o ambiente registrado no experimento. Para uma reprodução controlada, fixe e registre as dependências efetivamente disponíveis no ambiente utilizado.

## Dados e preparação

A série horária usada pelo experimento é indicada nos manifestos como `dados/tratado/series_horarias.csv`; as saídas são organizadas nos diretórios `resultados/baselines`, `resultados/principal` e `resultados/reproducao`.

Os dados brutos e derivados devem ser publicados apenas quando sua redistribuição estiver autorizada. Caso os arquivos de dados não estejam incluídos neste repositório, obtenha-os da fonte pública original e execute o processo de preparação disponibilizado no código do projeto para gerar a entrada esperada. Preserve a procedência, o período, as transformações e as configurações utilizadas.

**Tratamento importante:** nos dados avaliados, registros ausentes foram tratados como zero em parte da preparação. Essa regra pode confundir ausência de lentidão com ausência de monitoramento ou de registro; ela constitui uma limitação da análise e precisa ser considerada na interpretação dos resultados.

## Como conferir os resultados e os testes

Os resultados devem ser lidos em conjunto:

- `metricas_por_janela.csv`: métricas de cada janela de teste;
- `metricas_por_serie.csv`: métricas agregadas por série e método;
- `previsoes.csv`: previsões e valores observados por passo do horizonte;
- `resumo_modelos.csv`: resumo agregado por método;
- `execucao.json`: parâmetros e versões informados para uma execução;
- figuras PNG: visualizações das previsões e dos erros;
- análise de robustez: resultados após excluir as três séries zeradas no teste;
- log de testes: registro dos testes automatizados executados.

Os registros fornecidos para o projeto reportam 23 testes automatizados aprovados. Esse resultado verifica os comportamentos cobertos pelos testes, mas não comprova por si só a validade externa do modelo nem a generalização para todos os corredores de São Paulo.

Para executar os testes automatizados, a execução registrada utilizou o módulo `unittest` do Python:

```powershell
python -m unittest -v
```

Para reproduzir os experimentos completos, utilize o ponto de entrada de execução existente no código deste repositório e mantenha os parâmetros do manifesto correspondentes a cada cenário (`baselines`, `principal` e `reproducao`). Os nomes e argumentos do script de experimento devem corresponder aos arquivos efetivamente presentes no repositório; não se deve presumir um comando que não esteja documentado pelo código.

## Limitações

- A avaliação principal cobre 35 séries selecionadas e um período histórico específico; ela não comprova a mesma precisão em toda a malha viária de São Paulo ou em outros períodos.
- A avaliação é retrospectiva e utiliza dados horários agregados, não previsões operacionais em tempo real.
- A ausência de registro tratada como zero pode afetar as métricas.
- O desempenho varia por série e por passo do horizonte; a média sozinha não representa todos os casos.
- As fontes Metrô OD 2023 e Infosiga podem apoiar a contextualização da mobilidade, mas não foram entradas do modelo univariado Chronos-2 neste experimento.
- A análise não inclui teste formal de significância estatística entre os modelos.
- A consulta tabular e a classificação de criticidade previstas para o produto completo não devem ser consideradas validadas apenas com base neste experimento de previsão.

## Referências

- Ansari, A. F. et al. (2025). *Chronos-2: From Univariate to Universal Forecasting*. https://arxiv.org/abs/2510.15821
- Amazon. *Chronos-2 — modelo pré-treinado*. https://huggingface.co/amazon/chronos-2
- Companhia de Engenharia de Tráfego (CET) de São Paulo. Dados públicos de trânsito/lentidão consultados para a pesquisa. Consulte a documentação e as condições da fonte original antes de redistribuir dados.

## Estado do projeto

Este é um artefato de pesquisa acadêmica em desenvolvimento. Ao publicar uma nova versão, atualize este README, os arquivos de resultados, as versões do ambiente e os comandos de execução para que correspondam ao código e aos dados efetivamente usados.
