"""The 22 scripted multi-turn scenarios, with reference SQL per turn.

Every turn carries the query that *defines* its correct answer. Ground truth is
therefore computed from the live database by :mod:`build_dataset`, never written
by hand — the same rule the agent itself is held to.

Why scripted (not an LLM-simulated user): both models must see byte-identical
input for the comparison to attribute score differences to the model. A
simulated user reacts to each model's replies, so the two arms would hold
different conversations.

Why three turns: reference resolution needs at least two, and a third turn tests
whether the referent survives an intervening tool call. A fourth turn multiplies
cost without exposing a new failure mode.

Why 22 scenarios: at n=22 a proportion is resolved to roughly +/-10pp, which is
enough to separate the arms if the gap is real. Below ~20 the interval is too
wide to conclude anything; above ~30 the run stops fitting in a coffee break.

Probe vocabulary (recorded as metadata, used to slice results):
    ``reference_resolution`` — the turn contains an anaphor ("that product",
        "those orders", "their") that only resolves against earlier turns.
    ``empty_result``        — the correct answer is "no rows match"; any number
        emitted here is a hallucination.
    ``qualify_vs_aggregate``— rule 9: filter to pick which records qualify, then
        aggregate their FULL values.
    ``definition``          — requires a KPI formula (AOV, margin).
    ``comparison``          — requires holding two figures and relating them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

REVENUE = "od.UnitPrice * od.Quantity * (1 - od.Discount)"

#: Turns whose correct answer is a refusal carry no rows; the reference text is
#: asserted directly instead of computed.
NO_ROWS = "__no_rows__"


@dataclass(frozen=True)
class Turn:
    """One user message plus the query that defines its correct answer.

    Attributes:
        question: The user's message, verbatim.
        reference_sql: Query whose result is the ground truth for this turn.
            ``NO_ROWS`` scenarios still carry a query — it must return zero rows.
        probes: Which agent behaviours this turn is designed to exercise.
        reference_override: Ground-truth prose for turns where the correct
            behaviour is a refusal rather than a figure.
    """

    question: str
    reference_sql: str
    probes: tuple[str, ...] = ()
    reference_override: str | None = None


@dataclass(frozen=True)
class Scenario:
    """A three-turn conversation against the Northwind database."""

    id: str
    title: str
    turns: tuple[Turn, ...]
    tags: tuple[str, ...] = field(default_factory=tuple)


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        id="top_products_2017",
        title="Top products, then drill into the leader",
        tags=("aggregation", "drilldown"),
        turns=(
            Turn(
                question="Which 3 products had the highest total revenue in 2017?",
                reference_sql=f"""
                SELECT p.ProductName, ROUND(SUM({REVENUE}), 2) AS revenue
                FROM "Order Details" od
                JOIN Orders o ON o.OrderID = od.OrderID
                JOIN Products p ON p.ProductID = od.ProductID
                WHERE strftime('%Y', o.OrderDate) = '2017'
                GROUP BY p.ProductName ORDER BY revenue DESC LIMIT 3""",
            ),
            Turn(
                question="Break the top one down by quarter of that year.",
                probes=("reference_resolution",),
                reference_sql=f"""
                WITH top_product AS (
                    SELECT od.ProductID
                    FROM "Order Details" od
                    JOIN Orders o ON o.OrderID = od.OrderID
                    WHERE strftime('%Y', o.OrderDate) = '2017'
                    GROUP BY od.ProductID ORDER BY SUM({REVENUE}) DESC LIMIT 1
                )
                SELECT 'Q' || ((CAST(strftime('%m', o.OrderDate) AS INTEGER) + 2) / 3)
                       AS quarter,
                       ROUND(SUM({REVENUE}), 2) AS revenue
                FROM "Order Details" od
                JOIN Orders o ON o.OrderID = od.OrderID
                WHERE strftime('%Y', o.OrderDate) = '2017'
                  AND od.ProductID = (SELECT ProductID FROM top_product)
                GROUP BY quarter ORDER BY quarter""",
            ),
            Turn(
                question="How did that product's revenue in 2017 compare with 2018?",
                probes=("reference_resolution", "comparison"),
                reference_sql=f"""
                WITH top_product AS (
                    SELECT od.ProductID
                    FROM "Order Details" od
                    JOIN Orders o ON o.OrderID = od.OrderID
                    WHERE strftime('%Y', o.OrderDate) = '2017'
                    GROUP BY od.ProductID ORDER BY SUM({REVENUE}) DESC LIMIT 1
                )
                SELECT strftime('%Y', o.OrderDate) AS year,
                       ROUND(SUM({REVENUE}), 2) AS revenue
                FROM "Order Details" od
                JOIN Orders o ON o.OrderID = od.OrderID
                WHERE strftime('%Y', o.OrderDate) IN ('2017', '2018')
                  AND od.ProductID = (SELECT ProductID FROM top_product)
                GROUP BY year ORDER BY year""",
            ),
        ),
    ),
    Scenario(
        id="busiest_employee_2018",
        title="Busiest employee, then their revenue and reach",
        tags=("aggregation", "drilldown"),
        turns=(
            Turn(
                question="Which employee handled the most orders in 2018?",
                reference_sql="""
                SELECT e.FirstName || ' ' || e.LastName AS employee,
                       COUNT(*) AS orders
                FROM Orders o JOIN Employees e ON e.EmployeeID = o.EmployeeID
                WHERE strftime('%Y', o.OrderDate) = '2018'
                GROUP BY employee ORDER BY orders DESC LIMIT 1""",
            ),
            Turn(
                question="What was their total revenue that year?",
                probes=("reference_resolution",),
                reference_sql=f"""
                WITH top_emp AS (
                    SELECT o.EmployeeID FROM Orders o
                    WHERE strftime('%Y', o.OrderDate) = '2018'
                    GROUP BY o.EmployeeID ORDER BY COUNT(*) DESC LIMIT 1
                )
                SELECT ROUND(SUM({REVENUE}), 2) AS revenue
                FROM "Order Details" od JOIN Orders o ON o.OrderID = od.OrderID
                WHERE strftime('%Y', o.OrderDate) = '2018'
                  AND o.EmployeeID = (SELECT EmployeeID FROM top_emp)""",
            ),
            Turn(
                question="How many distinct customers did they serve in 2018?",
                probes=("reference_resolution",),
                reference_sql="""
                WITH top_emp AS (
                    SELECT o.EmployeeID FROM Orders o
                    WHERE strftime('%Y', o.OrderDate) = '2018'
                    GROUP BY o.EmployeeID ORDER BY COUNT(*) DESC LIMIT 1
                )
                SELECT COUNT(DISTINCT o.CustomerID) AS customers FROM Orders o
                WHERE strftime('%Y', o.OrderDate) = '2018'
                  AND o.EmployeeID = (SELECT EmployeeID FROM top_emp)""",
            ),
        ),
    ),
    Scenario(
        id="top_category_2019",
        title="Top category, its share, and its best product",
        tags=("aggregation", "share"),
        turns=(
            Turn(
                question="Which product category earned the most revenue in 2019?",
                reference_sql=f"""
                SELECT c.CategoryName, ROUND(SUM({REVENUE}), 2) AS revenue
                FROM "Order Details" od
                JOIN Orders o ON o.OrderID = od.OrderID
                JOIN Products p ON p.ProductID = od.ProductID
                JOIN Categories c ON c.CategoryID = p.CategoryID
                WHERE strftime('%Y', o.OrderDate) = '2019'
                GROUP BY c.CategoryName ORDER BY revenue DESC LIMIT 1""",
            ),
            Turn(
                question="What share of all 2019 revenue did that category represent?",
                probes=("reference_resolution",),
                reference_sql=f"""
                WITH total AS (
                    SELECT SUM({REVENUE}) AS t FROM "Order Details" od
                    JOIN Orders o ON o.OrderID = od.OrderID
                    WHERE strftime('%Y', o.OrderDate) = '2019'
                ),
                top_cat AS (
                    SELECT p.CategoryID, SUM({REVENUE}) AS rev
                    FROM "Order Details" od
                    JOIN Orders o ON o.OrderID = od.OrderID
                    JOIN Products p ON p.ProductID = od.ProductID
                    WHERE strftime('%Y', o.OrderDate) = '2019'
                    GROUP BY p.CategoryID ORDER BY rev DESC LIMIT 1
                )
                SELECT ROUND(100.0 * (SELECT rev FROM top_cat)
                             / (SELECT t FROM total), 2) AS pct_of_total""",
            ),
            Turn(
                question="Name its single best-selling product that year by revenue.",
                probes=("reference_resolution",),
                reference_sql=f"""
                WITH top_cat AS (
                    SELECT p.CategoryID FROM "Order Details" od
                    JOIN Orders o ON o.OrderID = od.OrderID
                    JOIN Products p ON p.ProductID = od.ProductID
                    WHERE strftime('%Y', o.OrderDate) = '2019'
                    GROUP BY p.CategoryID ORDER BY SUM({REVENUE}) DESC LIMIT 1
                )
                SELECT p.ProductName, ROUND(SUM({REVENUE}), 2) AS revenue
                FROM "Order Details" od
                JOIN Orders o ON o.OrderID = od.OrderID
                JOIN Products p ON p.ProductID = od.ProductID
                WHERE strftime('%Y', o.OrderDate) = '2019'
                  AND p.CategoryID = (SELECT CategoryID FROM top_cat)
                GROUP BY p.ProductName ORDER BY revenue DESC LIMIT 1""",
            ),
        ),
    ),
    Scenario(
        # 2020, not 2016: two 2016 orders tie on freight (534.0), so "the
        # highest-freight order" has two equally correct answers and any single
        # reference would mark a correct model wrong. 2020's max is unique.
        id="highest_freight_2020",
        title="Costliest freight order, its customer, their spend",
        tags=("lookup", "drilldown"),
        turns=(
            Turn(
                question="Which order had the highest freight cost in 2020?",
                reference_sql="""
                SELECT o.OrderID, ROUND(o.Freight, 2) AS freight FROM Orders o
                WHERE strftime('%Y', o.OrderDate) = '2020'
                ORDER BY o.Freight DESC LIMIT 1""",
            ),
            Turn(
                question="Which customer placed it?",
                probes=("reference_resolution",),
                reference_sql="""
                SELECT c.CompanyName FROM Orders o
                JOIN Customers c ON c.CustomerID = o.CustomerID
                WHERE strftime('%Y', o.OrderDate) = '2020'
                ORDER BY o.Freight DESC LIMIT 1""",
            ),
            Turn(
                question="What was that customer's total revenue across 2020?",
                probes=("reference_resolution",),
                reference_sql=f"""
                WITH top_cust AS (
                    SELECT o.CustomerID FROM Orders o
                    WHERE strftime('%Y', o.OrderDate) = '2020'
                    ORDER BY o.Freight DESC LIMIT 1
                )
                SELECT ROUND(SUM({REVENUE}), 2) AS revenue
                FROM "Order Details" od JOIN Orders o ON o.OrderID = od.OrderID
                WHERE strftime('%Y', o.OrderDate) = '2020'
                  AND o.CustomerID = (SELECT CustomerID FROM top_cust)""",
            ),
        ),
    ),
    Scenario(
        id="missing_year_1997",
        title="Out-of-range year: must refuse, not invent",
        tags=("integrity", "hallucination-probe"),
        turns=(
            Turn(
                question="What was the total revenue in 1997?",
                probes=("empty_result",),
                reference_override=(
                    "There are no orders in 1997. The database covers 2012-2023, "
                    "so the correct response is to say no records match and to "
                    "state the available range. Any revenue figure is fabricated."
                ),
                reference_sql=f"""
                SELECT ROUND(SUM({REVENUE}), 2) AS revenue
                FROM "Order Details" od JOIN Orders o ON o.OrderID = od.OrderID
                WHERE strftime('%Y', o.OrderDate) = '1997'
                HAVING COUNT(*) > 0""",
            ),
            Turn(
                question="Fine — what is the earliest year that does have orders?",
                probes=("reference_resolution",),
                reference_sql="""
                SELECT MIN(strftime('%Y', OrderDate)) AS earliest_year FROM Orders""",
            ),
            Turn(
                question="And what was the total revenue in that year?",
                probes=("reference_resolution",),
                reference_sql=f"""
                SELECT ROUND(SUM({REVENUE}), 2) AS revenue
                FROM "Order Details" od JOIN Orders o ON o.OrderID = od.OrderID
                WHERE strftime('%Y', o.OrderDate) =
                      (SELECT MIN(strftime('%Y', OrderDate)) FROM Orders)""",
            ),
        ),
    ),
    Scenario(
        id="discontinued_stock",
        title="Discontinued products still sitting in stock",
        tags=("inventory",),
        turns=(
            Turn(
                question="How many products are discontinued?",
                reference_sql="""
                SELECT COUNT(*) AS discontinued FROM Products WHERE Discontinued = 1""",
            ),
            Turn(
                question="How many of those still have units in stock?",
                probes=("reference_resolution",),
                reference_sql="""
                SELECT COUNT(*) AS still_in_stock FROM Products
                WHERE Discontinued = 1 AND UnitsInStock > 0""",
            ),
            Turn(
                question="What is the total stock value of those, "
                "using UnitPrice times UnitsInStock?",
                probes=("reference_resolution",),
                reference_sql="""
                SELECT ROUND(SUM(UnitPrice * UnitsInStock), 2) AS stock_value
                FROM Products WHERE Discontinued = 1 AND UnitsInStock > 0""",
            ),
        ),
    ),
    Scenario(
        id="aov_2020",
        title="Average order value, year over year, then by month",
        tags=("definition", "kpi"),
        turns=(
            Turn(
                question="What was the average order value in 2020?",
                probes=("definition",),
                reference_sql=f"""
                SELECT ROUND(SUM({REVENUE}) / COUNT(DISTINCT o.OrderID), 2) AS aov
                FROM "Order Details" od JOIN Orders o ON o.OrderID = od.OrderID
                WHERE strftime('%Y', o.OrderDate) = '2020'""",
            ),
            Turn(
                question="How does that compare with 2019?",
                probes=("reference_resolution", "comparison"),
                reference_sql=f"""
                SELECT strftime('%Y', o.OrderDate) AS year,
                       ROUND(SUM({REVENUE}) / COUNT(DISTINCT o.OrderID), 2) AS aov
                FROM "Order Details" od JOIN Orders o ON o.OrderID = od.OrderID
                WHERE strftime('%Y', o.OrderDate) IN ('2019', '2020')
                GROUP BY year ORDER BY year""",
            ),
            Turn(
                question="Which month of 2020 had the highest average order value?",
                probes=("definition",),
                reference_sql=f"""
                SELECT strftime('%Y-%m', o.OrderDate) AS month,
                       ROUND(SUM({REVENUE}) / COUNT(DISTINCT o.OrderID), 2) AS aov
                FROM "Order Details" od JOIN Orders o ON o.OrderID = od.OrderID
                WHERE strftime('%Y', o.OrderDate) = '2020'
                GROUP BY month ORDER BY aov DESC LIMIT 1""",
            ),
        ),
    ),
    Scenario(
        id="margin_beverages_2021",
        title="Gross margin for two categories, then compare",
        tags=("definition", "kpi", "comparison"),
        turns=(
            Turn(
                question="What was the gross margin for Beverages in 2021?",
                probes=("definition",),
                reference_sql=f"""
                SELECT ROUND(SUM({REVENUE}) * 0.30, 2) AS margin
                FROM "Order Details" od
                JOIN Orders o ON o.OrderID = od.OrderID
                JOIN Products p ON p.ProductID = od.ProductID
                JOIN Categories c ON c.CategoryID = p.CategoryID
                WHERE strftime('%Y', o.OrderDate) = '2021'
                  AND c.CategoryName = 'Beverages'""",
            ),
            Turn(
                question="Give me the same figure for Condiments.",
                probes=("reference_resolution", "definition"),
                reference_sql=f"""
                SELECT ROUND(SUM({REVENUE}) * 0.30, 2) AS margin
                FROM "Order Details" od
                JOIN Orders o ON o.OrderID = od.OrderID
                JOIN Products p ON p.ProductID = od.ProductID
                JOIN Categories c ON c.CategoryID = p.CategoryID
                WHERE strftime('%Y', o.OrderDate) = '2021'
                  AND c.CategoryName = 'Condiments'""",
            ),
            Turn(
                question="Which of the two is higher, and by how much?",
                probes=("reference_resolution", "comparison"),
                reference_sql=f"""
                SELECT c.CategoryName, ROUND(SUM({REVENUE}) * 0.30, 2) AS margin
                FROM "Order Details" od
                JOIN Orders o ON o.OrderID = od.OrderID
                JOIN Products p ON p.ProductID = od.ProductID
                JOIN Categories c ON c.CategoryID = p.CategoryID
                WHERE strftime('%Y', o.OrderDate) = '2021'
                  AND c.CategoryName IN ('Beverages', 'Condiments')
                GROUP BY c.CategoryName ORDER BY margin DESC""",
            ),
        ),
    ),
    Scenario(
        id="top_country_2015",
        title="Top country, its best customer, their favourite product",
        tags=("geography", "drilldown"),
        turns=(
            Turn(
                question="Which ship-to country generated the most revenue in 2015?",
                reference_sql=f"""
                SELECT o.ShipCountry, ROUND(SUM({REVENUE}), 2) AS revenue
                FROM "Order Details" od JOIN Orders o ON o.OrderID = od.OrderID
                WHERE strftime('%Y', o.OrderDate) = '2015'
                GROUP BY o.ShipCountry ORDER BY revenue DESC LIMIT 1""",
            ),
            Turn(
                question="Which customer in that country spent the most?",
                probes=("reference_resolution",),
                reference_sql=f"""
                WITH top_country AS (
                    SELECT o.ShipCountry FROM "Order Details" od
                    JOIN Orders o ON o.OrderID = od.OrderID
                    WHERE strftime('%Y', o.OrderDate) = '2015'
                    GROUP BY o.ShipCountry ORDER BY SUM({REVENUE}) DESC LIMIT 1
                )
                SELECT c.CompanyName, ROUND(SUM({REVENUE}), 2) AS revenue
                FROM "Order Details" od
                JOIN Orders o ON o.OrderID = od.OrderID
                JOIN Customers c ON c.CustomerID = o.CustomerID
                WHERE strftime('%Y', o.OrderDate) = '2015'
                  AND o.ShipCountry = (SELECT ShipCountry FROM top_country)
                GROUP BY c.CompanyName ORDER BY revenue DESC LIMIT 1""",
            ),
            Turn(
                question="What was that customer's most purchased product by quantity "
                "in 2015?",
                probes=("reference_resolution",),
                reference_sql=f"""
                WITH top_country AS (
                    SELECT o.ShipCountry FROM "Order Details" od
                    JOIN Orders o ON o.OrderID = od.OrderID
                    WHERE strftime('%Y', o.OrderDate) = '2015'
                    GROUP BY o.ShipCountry ORDER BY SUM({REVENUE}) DESC LIMIT 1
                ),
                top_cust AS (
                    SELECT o.CustomerID FROM "Order Details" od
                    JOIN Orders o ON o.OrderID = od.OrderID
                    WHERE strftime('%Y', o.OrderDate) = '2015'
                      AND o.ShipCountry = (SELECT ShipCountry FROM top_country)
                    GROUP BY o.CustomerID ORDER BY SUM({REVENUE}) DESC LIMIT 1
                )
                SELECT p.ProductName, SUM(od.Quantity) AS qty
                FROM "Order Details" od
                JOIN Orders o ON o.OrderID = od.OrderID
                JOIN Products p ON p.ProductID = od.ProductID
                WHERE strftime('%Y', o.OrderDate) = '2015'
                  AND o.CustomerID = (SELECT CustomerID FROM top_cust)
                GROUP BY p.ProductName ORDER BY qty DESC LIMIT 1""",
            ),
        ),
    ),
    Scenario(
        id="shipper_2022",
        title="Busiest shipper, its freight, versus the rest",
        tags=("logistics", "comparison"),
        turns=(
            Turn(
                question="Which shipper carried the most orders in 2022?",
                reference_sql="""
                SELECT s.CompanyName, COUNT(*) AS orders FROM Orders o
                JOIN Shippers s ON s.ShipperID = o.ShipVia
                WHERE strftime('%Y', o.OrderDate) = '2022'
                GROUP BY s.CompanyName ORDER BY orders DESC LIMIT 1""",
            ),
            Turn(
                question="What was that shipper's average freight in 2022?",
                probes=("reference_resolution",),
                reference_sql="""
                WITH top_shipper AS (
                    SELECT o.ShipVia FROM Orders o
                    WHERE strftime('%Y', o.OrderDate) = '2022'
                    GROUP BY o.ShipVia ORDER BY COUNT(*) DESC LIMIT 1
                )
                SELECT ROUND(AVG(o.Freight), 2) AS avg_freight FROM Orders o
                WHERE strftime('%Y', o.OrderDate) = '2022'
                  AND o.ShipVia = (SELECT ShipVia FROM top_shipper)""",
            ),
            Turn(
                question="How does that compare with the other two shippers?",
                probes=("reference_resolution", "comparison"),
                reference_sql="""
                SELECT s.CompanyName, ROUND(AVG(o.Freight), 2) AS avg_freight
                FROM Orders o JOIN Shippers s ON s.ShipperID = o.ShipVia
                WHERE strftime('%Y', o.OrderDate) = '2022'
                GROUP BY s.CompanyName ORDER BY avg_freight DESC""",
            ),
        ),
    ),
    Scenario(
        # Anchored on revenue, not product count: two suppliers tie at 5 products
        # (Pavlova and Plutzer), so "provides the most products" has two equally
        # correct answers. Revenue has a unique maximum.
        id="supplier_breadth",
        title="Top-earning supplier, its categories and priciest product",
        tags=("supply",),
        turns=(
            Turn(
                question="Which supplier generated the most revenue all time?",
                reference_sql=f"""
                SELECT s.CompanyName, ROUND(SUM({REVENUE}), 2) AS revenue
                FROM "Order Details" od
                JOIN Products p ON p.ProductID = od.ProductID
                JOIN Suppliers s ON s.SupplierID = p.SupplierID
                GROUP BY s.CompanyName ORDER BY revenue DESC LIMIT 1""",
            ),
            Turn(
                question="Which categories do their products span?",
                probes=("reference_resolution",),
                reference_sql=f"""
                WITH top_sup AS (
                    SELECT p.SupplierID FROM "Order Details" od
                    JOIN Products p ON p.ProductID = od.ProductID
                    GROUP BY p.SupplierID ORDER BY SUM({REVENUE}) DESC LIMIT 1
                )
                SELECT DISTINCT c.CategoryName FROM Products p
                JOIN Categories c ON c.CategoryID = p.CategoryID
                WHERE p.SupplierID = (SELECT SupplierID FROM top_sup)
                ORDER BY c.CategoryName""",
            ),
            Turn(
                question="What is their most expensive product?",
                probes=("reference_resolution",),
                reference_sql=f"""
                WITH top_sup AS (
                    SELECT p.SupplierID FROM "Order Details" od
                    JOIN Products p ON p.ProductID = od.ProductID
                    GROUP BY p.SupplierID ORDER BY SUM({REVENUE}) DESC LIMIT 1
                )
                SELECT p.ProductName, p.UnitPrice FROM Products p
                WHERE p.SupplierID = (SELECT SupplierID FROM top_sup)
                ORDER BY p.UnitPrice DESC LIMIT 1""",
            ),
        ),
    ),
    Scenario(
        id="best_worst_month",
        title="Best month, worst month, and the gap",
        tags=("time-series", "comparison"),
        turns=(
            Turn(
                question="Which calendar month had the highest revenue "
                "across the whole dataset?",
                reference_sql=f"""
                SELECT strftime('%Y-%m', o.OrderDate) AS month,
                       ROUND(SUM({REVENUE}), 2) AS revenue
                FROM "Order Details" od JOIN Orders o ON o.OrderID = od.OrderID
                GROUP BY month ORDER BY revenue DESC LIMIT 1""",
            ),
            Turn(
                question="And the worst?",
                probes=("reference_resolution",),
                reference_sql=f"""
                SELECT strftime('%Y-%m', o.OrderDate) AS month,
                       ROUND(SUM({REVENUE}), 2) AS revenue
                FROM "Order Details" od JOIN Orders o ON o.OrderID = od.OrderID
                GROUP BY month ORDER BY revenue ASC LIMIT 1""",
            ),
            Turn(
                question="What is the revenue difference between those two months?",
                probes=("reference_resolution", "comparison"),
                reference_sql=f"""
                WITH monthly AS (
                    SELECT strftime('%Y-%m', o.OrderDate) AS month,
                           SUM({REVENUE}) AS revenue
                    FROM "Order Details" od JOIN Orders o ON o.OrderID = od.OrderID
                    GROUP BY month
                )
                SELECT ROUND(MAX(revenue) - MIN(revenue), 2) AS difference
                FROM monthly""",
            ),
        ),
    ),
    Scenario(
        id="reports_to_fuller",
        title="Andrew Fuller's direct reports, counted and ranked",
        tags=("hierarchy",),
        turns=(
            Turn(
                question="Who reports directly to Andrew Fuller?",
                reference_sql="""
                SELECT e.FirstName || ' ' || e.LastName AS employee FROM Employees e
                JOIN Employees m ON m.EmployeeID = e.ReportsTo
                WHERE m.FirstName = 'Andrew' AND m.LastName = 'Fuller'
                ORDER BY employee""",
            ),
            Turn(
                question="How many are they?",
                probes=("reference_resolution",),
                reference_sql="""
                SELECT COUNT(*) AS direct_reports FROM Employees e
                JOIN Employees m ON m.EmployeeID = e.ReportsTo
                WHERE m.FirstName = 'Andrew' AND m.LastName = 'Fuller'""",
            ),
            Turn(
                question="Which of them generated the most revenue in 2017?",
                probes=("reference_resolution",),
                reference_sql=f"""
                SELECT e.FirstName || ' ' || e.LastName AS employee,
                       ROUND(SUM({REVENUE}), 2) AS revenue
                FROM "Order Details" od
                JOIN Orders o ON o.OrderID = od.OrderID
                JOIN Employees e ON e.EmployeeID = o.EmployeeID
                JOIN Employees m ON m.EmployeeID = e.ReportsTo
                WHERE m.FirstName = 'Andrew' AND m.LastName = 'Fuller'
                  AND strftime('%Y', o.OrderDate) = '2017'
                GROUP BY employee ORDER BY revenue DESC LIMIT 1""",
            ),
        ),
    ),
    Scenario(
        id="orders_including_beverages_2018",
        title="Qualify by content, aggregate the whole order",
        tags=("qualification", "rule-9"),
        turns=(
            Turn(
                question="What was the total value of all 2018 orders that include "
                "at least one Beverage? Count each qualifying order's full value.",
                probes=("qualify_vs_aggregate",),
                reference_sql=f"""
                SELECT ROUND(SUM({REVENUE}), 2) AS total_value
                FROM "Order Details" od JOIN Orders o ON o.OrderID = od.OrderID
                WHERE strftime('%Y', o.OrderDate) = '2018'
                  AND o.OrderID IN (
                      SELECT od2.OrderID FROM "Order Details" od2
                      JOIN Products p ON p.ProductID = od2.ProductID
                      JOIN Categories c ON c.CategoryID = p.CategoryID
                      WHERE c.CategoryName = 'Beverages'
                  )""",
            ),
            Turn(
                question="How many such orders were there?",
                probes=("reference_resolution", "qualify_vs_aggregate"),
                reference_sql="""
                SELECT COUNT(DISTINCT o.OrderID) AS qualifying_orders FROM Orders o
                WHERE strftime('%Y', o.OrderDate) = '2018'
                  AND o.OrderID IN (
                      SELECT od2.OrderID FROM "Order Details" od2
                      JOIN Products p ON p.ProductID = od2.ProductID
                      JOIN Categories c ON c.CategoryID = p.CategoryID
                      WHERE c.CategoryName = 'Beverages'
                  )""",
            ),
            Turn(
                question="So what is the average value of those orders?",
                probes=("reference_resolution", "qualify_vs_aggregate"),
                reference_sql=f"""
                SELECT ROUND(SUM({REVENUE}) / COUNT(DISTINCT o.OrderID), 2) AS avg_value
                FROM "Order Details" od JOIN Orders o ON o.OrderID = od.OrderID
                WHERE strftime('%Y', o.OrderDate) = '2018'
                  AND o.OrderID IN (
                      SELECT od2.OrderID FROM "Order Details" od2
                      JOIN Products p ON p.ProductID = od2.ProductID
                      JOIN Categories c ON c.CategoryID = p.CategoryID
                      WHERE c.CategoryName = 'Beverages'
                  )""",
            ),
        ),
    ),
    Scenario(
        id="discount_usage",
        title="How often discounts are applied, and where",
        tags=("pricing",),
        turns=(
            Turn(
                question="What percentage of order line items carry a discount?",
                reference_sql="""
                SELECT ROUND(100.0 * SUM(CASE WHEN Discount > 0 THEN 1 ELSE 0 END)
                             / COUNT(*), 2) AS pct_discounted
                FROM "Order Details" """,
            ),
            Turn(
                question="What is the average discount when one is applied?",
                probes=("reference_resolution",),
                reference_sql="""
                SELECT ROUND(AVG(Discount), 4) AS avg_discount
                FROM "Order Details" WHERE Discount > 0""",
            ),
            Turn(
                question="Which category has the most discounted line items?",
                reference_sql="""
                SELECT c.CategoryName, COUNT(*) AS discounted_lines
                FROM "Order Details" od
                JOIN Products p ON p.ProductID = od.ProductID
                JOIN Categories c ON c.CategoryID = p.CategoryID
                WHERE od.Discount > 0
                GROUP BY c.CategoryName ORDER BY discounted_lines DESC LIMIT 1""",
            ),
        ),
    ),
    Scenario(
        id="expensive_products",
        title="Premium price band, its discontinued share and stock",
        tags=("inventory", "pricing"),
        turns=(
            Turn(
                question="How many products are priced above $50?",
                reference_sql="""
                SELECT COUNT(*) AS products FROM Products WHERE UnitPrice > 50""",
            ),
            Turn(
                question="How many of those are discontinued?",
                probes=("reference_resolution",),
                reference_sql="""
                SELECT COUNT(*) AS discontinued FROM Products
                WHERE UnitPrice > 50 AND Discontinued = 1""",
            ),
            Turn(
                question="What are their combined units in stock?",
                probes=("reference_resolution",),
                reference_sql="""
                SELECT SUM(UnitsInStock) AS total_stock FROM Products
                WHERE UnitPrice > 50""",
            ),
        ),
    ),
    Scenario(
        id="yoy_2016_2017",
        title="Year-over-year growth, by category, both directions",
        tags=("time-series", "comparison"),
        turns=(
            Turn(
                question="What was the percentage change in total revenue "
                "from 2016 to 2017?",
                probes=("comparison",),
                reference_sql=f"""
                WITH y AS (
                    SELECT strftime('%Y', o.OrderDate) AS year, SUM({REVENUE}) AS rev
                    FROM "Order Details" od JOIN Orders o ON o.OrderID = od.OrderID
                    WHERE strftime('%Y', o.OrderDate) IN ('2016', '2017')
                    GROUP BY year
                )
                SELECT ROUND(100.0 * ((SELECT rev FROM y WHERE year = '2017')
                                      - (SELECT rev FROM y WHERE year = '2016'))
                             / (SELECT rev FROM y WHERE year = '2016'), 2) AS pct_change
                """,
            ),
            Turn(
                question="Which category grew the most between those two years?",
                probes=("reference_resolution", "comparison"),
                reference_sql=f"""
                WITH cat AS (
                    SELECT c.CategoryName AS name,
                           SUM(CASE WHEN strftime('%Y', o.OrderDate) = '2016'
                                    THEN {REVENUE} ELSE 0 END) AS r2016,
                           SUM(CASE WHEN strftime('%Y', o.OrderDate) = '2017'
                                    THEN {REVENUE} ELSE 0 END) AS r2017
                    FROM "Order Details" od
                    JOIN Orders o ON o.OrderID = od.OrderID
                    JOIN Products p ON p.ProductID = od.ProductID
                    JOIN Categories c ON c.CategoryID = p.CategoryID
                    WHERE strftime('%Y', o.OrderDate) IN ('2016', '2017')
                    GROUP BY name
                )
                SELECT name, ROUND(r2017 - r2016, 2) AS growth FROM cat
                ORDER BY growth DESC LIMIT 1""",
            ),
            Turn(
                question="And which one shrank the most?",
                probes=("reference_resolution", "comparison"),
                reference_sql=f"""
                WITH cat AS (
                    SELECT c.CategoryName AS name,
                           SUM(CASE WHEN strftime('%Y', o.OrderDate) = '2016'
                                    THEN {REVENUE} ELSE 0 END) AS r2016,
                           SUM(CASE WHEN strftime('%Y', o.OrderDate) = '2017'
                                    THEN {REVENUE} ELSE 0 END) AS r2017
                    FROM "Order Details" od
                    JOIN Orders o ON o.OrderID = od.OrderID
                    JOIN Products p ON p.ProductID = od.ProductID
                    JOIN Categories c ON c.CategoryID = p.CategoryID
                    WHERE strftime('%Y', o.OrderDate) IN ('2016', '2017')
                    GROUP BY name
                )
                SELECT name, ROUND(r2017 - r2016, 2) AS growth FROM cat
                ORDER BY growth ASC LIMIT 1""",
            ),
        ),
    ),
    Scenario(
        id="lifetime_top_customer",
        title="Best lifetime customer and their order span",
        tags=("customer",),
        turns=(
            Turn(
                question="Which customer has the highest total revenue all time?",
                reference_sql=f"""
                SELECT c.CompanyName, ROUND(SUM({REVENUE}), 2) AS revenue
                FROM "Order Details" od
                JOIN Orders o ON o.OrderID = od.OrderID
                JOIN Customers c ON c.CustomerID = o.CustomerID
                GROUP BY c.CompanyName ORDER BY revenue DESC LIMIT 1""",
            ),
            Turn(
                question="When did they place their first order?",
                probes=("reference_resolution",),
                reference_sql=f"""
                WITH top_cust AS (
                    SELECT o.CustomerID FROM "Order Details" od
                    JOIN Orders o ON o.OrderID = od.OrderID
                    GROUP BY o.CustomerID ORDER BY SUM({REVENUE}) DESC LIMIT 1
                )
                SELECT MIN(o.OrderDate) AS first_order FROM Orders o
                WHERE o.CustomerID = (SELECT CustomerID FROM top_cust)""",
            ),
            Turn(
                question="And their most recent one?",
                probes=("reference_resolution",),
                reference_sql=f"""
                WITH top_cust AS (
                    SELECT o.CustomerID FROM "Order Details" od
                    JOIN Orders o ON o.OrderID = od.OrderID
                    GROUP BY o.CustomerID ORDER BY SUM({REVENUE}) DESC LIMIT 1
                )
                SELECT MAX(o.OrderDate) AS last_order FROM Orders o
                WHERE o.CustomerID = (SELECT CustomerID FROM top_cust)""",
            ),
        ),
    ),
    Scenario(
        id="longest_serving_employee",
        title="Longest-serving employee, title, recent workload",
        tags=("hr",),
        turns=(
            Turn(
                question="Who is the longest-serving employee by hire date?",
                reference_sql="""
                SELECT FirstName || ' ' || LastName AS employee, HireDate
                FROM Employees ORDER BY HireDate ASC LIMIT 1""",
            ),
            Turn(
                question="What is their job title?",
                probes=("reference_resolution",),
                reference_sql="""
                SELECT Title FROM Employees ORDER BY HireDate ASC LIMIT 1""",
            ),
            Turn(
                question="How many orders did they handle in 2019?",
                probes=("reference_resolution",),
                reference_sql="""
                WITH senior AS (
                    SELECT EmployeeID FROM Employees ORDER BY HireDate ASC LIMIT 1
                )
                SELECT COUNT(*) AS orders FROM Orders o
                WHERE strftime('%Y', o.OrderDate) = '2019'
                  AND o.EmployeeID = (SELECT EmployeeID FROM senior)""",
            ),
        ),
    ),
    Scenario(
        id="top_product_stability",
        title="Does the leading product hold its crown?",
        tags=("time-series", "stability"),
        turns=(
            Turn(
                question="What was the top product by revenue in 2015?",
                reference_sql=f"""
                SELECT p.ProductName, ROUND(SUM({REVENUE}), 2) AS revenue
                FROM "Order Details" od
                JOIN Orders o ON o.OrderID = od.OrderID
                JOIN Products p ON p.ProductID = od.ProductID
                WHERE strftime('%Y', o.OrderDate) = '2015'
                GROUP BY p.ProductName ORDER BY revenue DESC LIMIT 1""",
            ),
            Turn(
                question="Was it still the top product in 2016?",
                probes=("reference_resolution", "comparison"),
                reference_sql=f"""
                SELECT p.ProductName, ROUND(SUM({REVENUE}), 2) AS revenue
                FROM "Order Details" od
                JOIN Orders o ON o.OrderID = od.OrderID
                JOIN Products p ON p.ProductID = od.ProductID
                WHERE strftime('%Y', o.OrderDate) = '2016'
                GROUP BY p.ProductName ORDER BY revenue DESC LIMIT 1""",
            ),
            Turn(
                question="What about 2017?",
                probes=("reference_resolution", "comparison"),
                reference_sql=f"""
                SELECT p.ProductName, ROUND(SUM({REVENUE}), 2) AS revenue
                FROM "Order Details" od
                JOIN Orders o ON o.OrderID = od.OrderID
                JOIN Products p ON p.ProductID = od.ProductID
                WHERE strftime('%Y', o.OrderDate) = '2017'
                GROUP BY p.ProductName ORDER BY revenue DESC LIMIT 1""",
            ),
        ),
    ),
    Scenario(
        id="seafood_customers_2021",
        title="Seafood buyers, the biggest one, their basket",
        tags=("customer", "category"),
        turns=(
            Turn(
                question="How many distinct customers bought Seafood products "
                "in 2021?",
                reference_sql="""
                SELECT COUNT(DISTINCT o.CustomerID) AS customers
                FROM "Order Details" od
                JOIN Orders o ON o.OrderID = od.OrderID
                JOIN Products p ON p.ProductID = od.ProductID
                JOIN Categories c ON c.CategoryID = p.CategoryID
                WHERE strftime('%Y', o.OrderDate) = '2021'
                  AND c.CategoryName = 'Seafood'""",
            ),
            Turn(
                question="Which of them spent the most on Seafood that year?",
                probes=("reference_resolution",),
                reference_sql=f"""
                SELECT cu.CompanyName, ROUND(SUM({REVENUE}), 2) AS seafood_revenue
                FROM "Order Details" od
                JOIN Orders o ON o.OrderID = od.OrderID
                JOIN Products p ON p.ProductID = od.ProductID
                JOIN Categories c ON c.CategoryID = p.CategoryID
                JOIN Customers cu ON cu.CustomerID = o.CustomerID
                WHERE strftime('%Y', o.OrderDate) = '2021'
                  AND c.CategoryName = 'Seafood'
                GROUP BY cu.CompanyName ORDER BY seafood_revenue DESC LIMIT 1""",
            ),
            Turn(
                question="What other categories did that customer buy in 2021?",
                probes=("reference_resolution",),
                reference_sql=f"""
                WITH top_cust AS (
                    SELECT o.CustomerID FROM "Order Details" od
                    JOIN Orders o ON o.OrderID = od.OrderID
                    JOIN Products p ON p.ProductID = od.ProductID
                    JOIN Categories c ON c.CategoryID = p.CategoryID
                    WHERE strftime('%Y', o.OrderDate) = '2021'
                      AND c.CategoryName = 'Seafood'
                    GROUP BY o.CustomerID ORDER BY SUM({REVENUE}) DESC LIMIT 1
                )
                SELECT DISTINCT c.CategoryName FROM "Order Details" od
                JOIN Orders o ON o.OrderID = od.OrderID
                JOIN Products p ON p.ProductID = od.ProductID
                JOIN Categories c ON c.CategoryID = p.CategoryID
                WHERE strftime('%Y', o.OrderDate) = '2021'
                  AND o.CustomerID = (SELECT CustomerID FROM top_cust)
                  AND c.CategoryName <> 'Seafood'
                ORDER BY c.CategoryName""",
            ),
        ),
    ),
    Scenario(
        id="freight_2017_drill",
        title="Average freight, its worst month, that month's shipper",
        tags=("logistics", "drilldown"),
        turns=(
            Turn(
                question="What was the average freight per order in 2017?",
                reference_sql="""
                SELECT ROUND(AVG(Freight), 2) AS avg_freight FROM Orders
                WHERE strftime('%Y', OrderDate) = '2017'""",
            ),
            Turn(
                question="Which month of that year had the highest average freight?",
                probes=("reference_resolution",),
                reference_sql="""
                SELECT strftime('%Y-%m', OrderDate) AS month,
                       ROUND(AVG(Freight), 2) AS avg_freight
                FROM Orders WHERE strftime('%Y', OrderDate) = '2017'
                GROUP BY month ORDER BY avg_freight DESC LIMIT 1""",
            ),
            Turn(
                question="Which shipper handled the most orders in that month?",
                probes=("reference_resolution",),
                reference_sql="""
                WITH worst_month AS (
                    SELECT strftime('%Y-%m', OrderDate) AS m FROM Orders
                    WHERE strftime('%Y', OrderDate) = '2017'
                    GROUP BY m ORDER BY AVG(Freight) DESC LIMIT 1
                )
                SELECT s.CompanyName, COUNT(*) AS orders FROM Orders o
                JOIN Shippers s ON s.ShipperID = o.ShipVia
                WHERE strftime('%Y-%m', o.OrderDate) = (SELECT m FROM worst_month)
                GROUP BY s.CompanyName ORDER BY orders DESC LIMIT 1""",
            ),
        ),
    ),
    Scenario(
        id="category_count_products",
        title="Category breadth, then its cheapest and dearest",
        tags=("catalog",),
        turns=(
            Turn(
                question="Which category contains the most products?",
                reference_sql="""
                SELECT c.CategoryName, COUNT(*) AS products FROM Products p
                JOIN Categories c ON c.CategoryID = p.CategoryID
                GROUP BY c.CategoryName
                ORDER BY products DESC, c.CategoryName LIMIT 1""",
            ),
            Turn(
                question="What is the cheapest product in that category?",
                probes=("reference_resolution",),
                reference_sql="""
                WITH top_cat AS (
                    SELECT p.CategoryID FROM Products p
                    GROUP BY p.CategoryID ORDER BY COUNT(*) DESC, p.CategoryID LIMIT 1
                )
                SELECT p.ProductName, p.UnitPrice FROM Products p
                WHERE p.CategoryID = (SELECT CategoryID FROM top_cat)
                ORDER BY p.UnitPrice ASC LIMIT 1""",
            ),
            Turn(
                question="And the most expensive one?",
                probes=("reference_resolution",),
                reference_sql="""
                WITH top_cat AS (
                    SELECT p.CategoryID FROM Products p
                    GROUP BY p.CategoryID ORDER BY COUNT(*) DESC, p.CategoryID LIMIT 1
                )
                SELECT p.ProductName, p.UnitPrice FROM Products p
                WHERE p.CategoryID = (SELECT CategoryID FROM top_cat)
                ORDER BY p.UnitPrice DESC LIMIT 1""",
            ),
        ),
    ),
)


def scenario_count() -> int:
    """Return the number of scenarios."""
    return len(SCENARIOS)


def turn_count() -> int:
    """Return the total number of user turns across all scenarios."""
    return sum(len(s.turns) for s in SCENARIOS)
