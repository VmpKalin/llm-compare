Produce ONLY valid JSON, no commentary:
{"items": [{"name": string, "price": number, "qty": number, "line_total": number}], "grand_total": number}
Rules: line_total = price * qty for each item; grand_total = sum of all line_totals. Compute every number yourself.
Items: 3 notebooks at 2.50 each; 2 pens at 1.20 each; 1 stapler at 7.99.
