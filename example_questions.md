Set A — Customer Drill-Down
Turn	Question	Answer
A1	Top 3 customers by revenue in 2017?	1. Wilman Kala — 839,491.63 / 2. La corne d'abondance — 785,318.35 / 3. IT — 764,450.32
A2	Gross margin for Wilman Kala in 2017?	251,847.49
A3	Which product category did Wilman Kala spend the most on?	Beverages — 183,095.00
Set B — Campaign Comparison
Turn	Question	Answer
B1	Total revenue during Summer Beverages 2017 (June only)?	2,995,440.24
B2	Total revenue during Winter Classics 2017 (December only)?	3,341,972.66 — Winter was higher
B3	Which campaign had the higher AOV?	Summer Beverages — AOV 22,354.03 vs Winter 21,018.70
Note the twist: Winter had higher total revenue, but Summer had higher AOV. Good test for whether the agent keeps the two metrics straight.

Set C — Employee Org Tree + Performance
Turn	Question	Answer
C1	How many employees report directly to Andrew Fuller?	5
C2	Among those 5, who had the highest total revenue in 2017?	Nancy Davolio — 4,846,677.85
C3	What was Nancy Davolio's top product category in 2017?	Beverages — 955,403.07
C2 is a potential trip-up: the existing benchmark hard_top_employee_beverages_rev_2017 returns Robert King — but that's for Beverages only. Across all categories, Nancy Davolio wins. Multi-turn context matters.

Set D — Product Lifecycle Drill-Down
Turn	Question	Answer
D1	Top 3 products by all-time revenue?	1. Côte de Blaye — 53,265,895.23 / 2. Thüringer Rostbratwurst — 24,623,469.23 / 3. Mishi Kobe Niku — 19,423,037.50
D2	Is Côte de Blaye discontinued?	No — Discontinued = 0, 17 units in stock
D3	Who supplies Côte de Blaye, and where?	Aux joyeux ecclésiastiques, Paris, France
Set E — Policy + Inventory
Turn	Question	Answer
E1	Return policy for Beverages?	14 days (unopened); no returns if opened (from RAG doc)
E2	How many Beverages products currently have units in stock?	12
E3	Total inventory value of those products at list price?	12,480.25 (SUM(UnitPrice * UnitsInStock))
E1 is pure RAG, E2 and E3 are pure SQL. The agent must bridge both in one conversation — and correctly carry the "Beverages + UnitsInStock > 0" filter from E2 into E3 without being told again.