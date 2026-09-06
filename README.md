<img width="1960" height="520" alt="chaintrace-horizontal" src="https://github.com/user-attachments/assets/a8b2bede-5f30-44a9-bba1-f0e77dad84e6" />

> [!IMPORTANT]
> ## ChainTrace v1.0.0 
<img width="813" height="497" alt="image" src="https://github.com/user-attachments/assets/20bad80e-f238-4c35-a5eb-04386535d3a5" />


**🧩 Overview**

ChainTrace v1.0.0 — a tool for finding connections between two blockchain addresses.
Automatically detects the network: Bitcoin, Ethereum, or TON.
Supports analysis of both a single address and two wallets simultaneously.
Works directly with real on-chain data through available APIs.

**🔍 Analysis**

Identifies the primary wallet — the address with the lower number of transactions within the selected time window.
Analyzes its direct incoming and outgoing transfers.
Finds counterparties that funded the wallet or received funds from it.
Loads the transaction history of counterparties to identify additional connections.
Connections are ranked primarily by the number and frequency of transfers, followed by transaction volume.

**🕸️ Transaction Web**

Builds a graph of interactions between the identified addresses.
Determines Intermediary 1 and Intermediary 2 with the strongest connections.
Displays transfer directions, number of transactions, assets, and dates.
Separately checks how the second wallet under investigation is connected to the identified intermediaries.
Finally, ChainTrace generates the actual interaction chain, for example:
Wallet 2 → Intermediary 2 → Intermediary 1 → Wallet 1.

**⛓️ Network Support**

Bitcoin — transaction analysis through BlockCypher.
Ethereum — transaction history retrieved through Etherscan or BlockCypher.
TON — analysis through TonAPI, with TonCenter as a fallback.
For TON, TonTransfer and JettonTransfer operations are taken into account, while swaps, deployments, and other actions are excluded from direct-transfer analysis.
Supports both TON raw and friendly addresses.

**🖥️ Interface**

Full-screen console interface with dynamic updates.
Color-coded wallets, intermediaries, transfer directions, and results.
Addresses are displayed in a convenient format with support for both shortened and full representations.
Includes a demo mode with a pre-built test chain.
Supports both interactive-menu execution and direct execution from CMD.

# RU
**🧩 Основное**

ChainTrace v1.0.0 — инструмент для поиска связи между двумя блокчейн-адресами.
Автоматически определяет сеть: Bitcoin, Ethereum или TON.
Поддерживается анализ как одного адреса, так и двух кошельков одновременно.
Работает напрямую с реальными on-chain данными через доступные API.

**🔍 Анализ**

Определяется основной кошелёк — адрес с меньшим количеством транзакций в выбранном временном окне.
Анализируются его прямые входящие и исходящие переводы.
Находятся контрагенты, которые пополняли кошелёк или получали от него средства.
Истории контрагентов дополнительно загружаются для поиска связей между ними.
Связи ранжируются в первую очередь по количеству и частоте переводов, затем по объёму.

**🕸️ Транзакционная паутина**

Строится граф взаимодействий между найденными адресами.
Определяются посредник 1 и посредник 2 с наиболее выраженной связью.
Показываются направления переводов, количество операций, активы и даты.
Отдельно проверяется, как второй исследуемый кошелёк связан с найденными посредниками.
В финале ChainTrace формирует реальную цепочку взаимодействий, например:
Кошелёк 2 → Посредник 2 → Посредник 1 → Кошелёк 1.

**⛓️ Поддержка сетей**

Bitcoin — анализ транзакций через BlockCypher.
Ethereum — получение истории через Etherscan или BlockCypher.
TON — анализ через TonAPI с резервным использованием TonCenter.
Для TON учитываются TonTransfer и JettonTransfer, а свопы, деплои и другие действия исключаются из анализа прямых переводов.
Поддерживается работа с TON raw и friendly-адресами.

**🖥️ Интерфейс**

Полноэкранный консольный интерфейс с динамическим обновлением.
Цветовая индикация кошельков, посредников, направлений и результатов.
Адреса отображаются в удобном формате с поддержкой сокращённого и полного представления.
Есть демо-режим с заранее построенной тестовой цепочкой.
Поддерживается запуск как через интерактивное меню, так и напрямую из CMD.
