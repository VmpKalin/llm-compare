Given tables:
  orders(id, customer_id, total_cents, created_at)
  customers(id, name, country)
Write ONE PostgreSQL query that returns, for each country, the number of customers who placed at least one order in 2025 and their total revenue in euros (total_cents/100), ordered by revenue descending. Return ONLY the SQL in a single code block.
