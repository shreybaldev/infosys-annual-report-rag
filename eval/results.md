# Eval results -- Infosys FY24 RAG

**Ran at (UTC):** 2026-06-02T07:33:13+00:00  
**Model:** gpt-4o-mini  
**Retrieval:** hybrid (vector + BM25, RRF k=60, top-8)  
**Source docs:**
- data/infosys_ar_fy24.pdf (Infosys FY24 Form 20-F, 296 pages)
- data/infosys_ar_fy25.pdf (Infosys FY25 Form 20-F, 359 pages)

## Summary

- Auto-pass: **11 / 14**
- Total API cost: **$0.01**
- Avg latency: **4.37 s/query**

Auto-grade is coarse (abstention correctness + expected-substring presence).
The per-question table below is the canonical scoring view -- edit the
**Manual** column after reading each answer.

## Per-question results

### `fl_001` (fact_lookup) -- auto: PASS

**Q:** Who is the current CEO of Infosys?

**Expected:** real answer containing `Salil Parekh`

**Answer:**

> The current CEO of Infosys is Salil Parekh, who also serves as the Managing Director (FY24, p. 82).

- abstained: `False`  - cited: `['FY24 p.82']`  - docs cited: `1`  - sources retrieved: `['FY25:94', 'FY25:86', 'FY24:85', 'FY24:84', 'FY25:85', 'FY25:83', 'FY25:281', 'FY24:82', 'FY25:265', 'FY25:236', 'FY25:272', 'FY24:273']`  - latency: 6.87s  - cost: $0.00068
- auto-grade reason: substring matched
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

### `fl_002` (fact_lookup) -- auto: PASS

**Q:** When was Infosys founded?

**Expected:** real answer containing `1981`

**Answer:**

> Infosys was founded on July 2, 1981, in Pune, Maharashtra, India, originally as Infosys Consultants Private Limited (FY25, p. 39).

- abstained: `False`  - cited: `['FY25 p.39']`  - docs cited: `1`  - sources retrieved: `['FY25:62', 'FY24:60', 'FY25:100', 'FY24:81', 'FY25:83', 'FY25:39', 'FY25:269', 'FY25:268', 'FY24:185', 'FY25:38', 'FY24:92', 'FY24:37']`  - latency: 3.27s  - cost: $0.0007
- auto-grade reason: substring matched
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

### `fl_003` (fact_lookup) -- auto: FAIL

**Q:** Where is Infosys's registered office located?

**Expected:** real answer containing `Bangalore`

**Answer:**

> Infosys's registered office is located at Electronics City, Hosur Road, Bengaluru, Karnataka, India 560 100 (FY24, p. 1).

- abstained: `False`  - cited: `['FY24 p.1']`  - docs cited: `1`  - sources retrieved: `['FY24:57', 'FY25:143', 'FY24:1', 'FY25:320', 'FY25:100', 'FY24:239', 'FY25:62', 'FY25:244', 'FY24:55', 'FY25:316', 'FY25:39', 'FY24:120']`  - latency: 3.96s  - cost: $0.00069
- auto-grade reason: answer missing expected substring 'Bangalore'
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

### `tr_001` (trend) -- auto: PASS

**Q:** How has Infosys's total employee count changed in recent years?

**Expected:** real answer containing `employees`

**Answer:**

> Between March 31, 2021, and March 31, 2025, Infosys's total employees grew from 259,619 to 323,578, representing a compound annualized growth rate of 5.7% (FY25, p. 39).

- abstained: `False`  - cited: `['FY25 p.39']`  - docs cited: `1`  - sources retrieved: `['FY24:36', 'FY24:176', 'FY25:100', 'FY25:177', 'FY25:39', 'FY25:80', 'FY25:57', 'FY24:78', 'FY25:38', 'FY24:68', 'FY24:106', 'FY25:71']`  - latency: 3.15s  - cost: $0.00071
- auto-grade reason: substring matched
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

### `tr_002` (trend) -- auto: FAIL

**Q:** What has been the trend in Infosys's R&D expenditure as a percentage of revenue?

**Expected:** real answer containing `R&D`

**Answer:**

> INSUFFICIENT_CONTEXT: The provided context does not include specific information about Infosys's R&D expenditure as a percentage of revenue for either fiscal year.

- abstained: `True`  - cited: `[]`  - docs cited: `0`  - sources retrieved: `['FY24:67', 'FY24:198', 'FY24:36', 'FY25:74', 'FY24:71', 'FY24:37', 'FY25:39', 'FY25:38', 'FY25:199', 'FY25:62', 'FY25:157', 'FY24:39']`  - latency: 3.09s  - cost: $0.00069
- auto-grade reason: abstained when an answer was expected
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

### `sy_001` (synthesis) -- auto: PASS

**Q:** Summarize Infosys's strategy around generative AI and Topaz from the report.

**Expected:** real answer containing `Topaz`

**Answer:**

> Infosys's strategy around generative AI and its Topaz platform focuses on leveraging AI to drive business transformation and enhance customer experiences. The company has trained over 275,000 employees on AI and has successfully delivered over 400 generative AI projects. Infosys Topaz® serves as an AI-first suite of services, solutions, and platforms that includes specialized models for domain adaptation and a Responsible AI framework. This approach aims to help enterprises improve adaptability, unlock efficiencies, and build connected ecosystems, ultimately enabling them to reimagine their business processes and achieve sustainable growth (FY25, pp. 39, 52; FY24, pp. 47, 50).

- abstained: `False`  - cited: `['FY25 p.39', 'FY25 p.52', 'FY24 p.47', 'FY24 p.50']`  - docs cited: `2`  - sources retrieved: `['FY25:53', 'FY25:40', 'FY24:50', 'FY24:47', 'FY25:52', 'FY25:62', 'FY24:38', 'FY25:49', 'FY24:39', 'FY24:46', 'FY24:37', 'FY25:39']`  - latency: 4.69s  - cost: $0.0007
- auto-grade reason: substring matched
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

### `sy_002` (synthesis) -- auto: PASS

**Q:** What are the main competitive and regulatory risks Infosys discloses?

**Expected:** real answer containing `competition`

**Answer:**

> Infosys identifies several competitive and regulatory risks in its annual reports:
> 
> **Competitive Risks:**
> - Intense competition in the technology services market could affect win rates and pricing, potentially reducing market share and revenues (FY25, p. 5).
> - A significant portion of revenues depends on a limited number of clients, meaning the loss of any major client could severely impact the business (FY25, p. 5).
> - The company must continuously anticipate and develop new services to keep pace with rapid technological changes and evolving client preferences (FY25, p. 12).
> 
> **Regulatory Risks:**
> - Compliance with various laws and regulations, including those related to climate action and environmental disclosures, poses risks. Non-compliance could lead to penalties and damage to reputation (FY24, p. 27).
> - Changes in tax benefits or incentives from the Government of India could adversely affect net income (FY25, p. 32).
> - The differing requirements of regulatory bodies, such as SEBI and NYSE, create complexities in governance and compliance (FY25, pp. 151-152). 
> 
> These risks highlight the challenges Infosys faces in maintaining its competitive edge while navigating a complex regulatory landscape.

- abstained: `False`  - cited: `['FY25 p.5', 'FY25 p.12', 'FY24 p.27', 'FY25 p.32', 'FY25 p.151']`  - docs cited: `2`  - sources retrieved: `['FY24:150', 'FY25:152', 'FY25:151', 'FY25:12', 'FY24:27', 'FY25:334', 'FY25:153', 'FY25:5', 'FY24:55', 'FY25:32', 'FY25:62', 'FY25:336']`  - latency: 6.98s  - cost: $0.00078
- auto-grade reason: substring matched
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

### `sy_003` (synthesis) -- auto: FAIL

**Q:** How does Infosys describe its approach to environmental sustainability and net-zero commitments?

**Expected:** real answer containing `carbon`

**Answer:**

> INSUFFICIENT_CONTEXT: The provided context does not include specific details about Infosys's approach to environmental sustainability and net-zero commitments.

- abstained: `True`  - cited: `[]`  - docs cited: `0`  - sources retrieved: `['FY25:100', 'FY25:28', 'FY24:37', 'FY25:39', 'FY24:60', 'FY24:26', 'FY25:153', 'FY24:39', 'FY25:62', 'FY25:300', 'FY25:42', 'FY25:52']`  - latency: 5.25s  - cost: $0.00067
- auto-grade reason: abstained when an answer was expected
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

### `tb_001` (table_lookup) -- auto: PASS

**Q:** What is the geographic revenue breakdown for Infosys (by region)?

**Expected:** real answer containing `North America`

**Answer:**

> For fiscal 2025, the geographic revenue breakdown for Infosys is as follows:
> 
> - North America: 57.9%
> - Europe: 29.8%
> - Rest of the World: 9.2%
> - India: 3.1%
> 
> This distribution reflects a total of 100.0% (FY25, p. 56).

- abstained: `False`  - cited: `['FY25 p.56']`  - docs cited: `1`  - sources retrieved: `['FY24:67', 'FY25:70', 'FY25:38', 'FY25:216', 'FY24:200', 'FY25:62', 'FY24:214', 'FY24:60', 'FY24:36', 'FY25:237', 'FY25:56', 'FY24:198']`  - latency: 4.7s  - cost: $0.00075
- auto-grade reason: substring matched
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

### `tb_002` (table_lookup) -- auto: PASS

**Q:** What were Infosys's operating segments and their relative revenue contributions?

**Expected:** real answer containing `Financial Services`

**Answer:**

> Infosys's operating segments and their relative revenue contributions for fiscal 2024 were as follows:
> 
> - **Financial Services**: 27.4%
> - **Retail**: 14.7%
> - **Communication**: 11.7%
> - **Energy, Utilities, Resources and Services**: 13.0%
> - **Manufacturing**: 14.5%
> - **Hi-Tech**: 8.1%
> - **Life Sciences**: 7.5%
> - **All Other Segments**: 3.1% (FY24, pp. 63, 67).

- abstained: `False`  - cited: `['FY24 p.63', 'FY24 p.67']`  - docs cited: `1`  - sources retrieved: `['FY24:233', 'FY25:201', 'FY24:67', 'FY24:198', 'FY25:237', 'FY25:65', 'FY24:200', 'FY24:63', 'FY24:36', 'FY24:232', 'FY24:54', 'FY25:304']`  - latency: 4.84s  - cost: $0.00079
- auto-grade reason: substring matched
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

### `ab_001` (abstention) -- auto: PASS

**Q:** What is Infosys's current stock price?

**Expected:** abstention (no answer in the doc)

**Answer:**

> INSUFFICIENT_CONTEXT: The provided context does not include information about Infosys's current stock price.

- abstained: `True`  - cited: `[]`  - docs cited: `0`  - sources retrieved: `['FY25:38', 'FY25:334', 'FY24:36', 'FY25:255', 'FY24:161', 'FY24:250', 'FY25:114', 'FY25:305', 'FY25:216', 'FY25:314', 'FY24:214', 'FY24:293']`  - latency: 2.36s  - cost: $0.00066
- auto-grade reason: abstained as expected
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

### `ab_002` (abstention) -- auto: PASS

**Q:** What were Infosys's revenue numbers for fiscal year 2026?

**Expected:** abstention (no answer in the doc)

**Answer:**

> INSUFFICIENT_CONTEXT: The provided context does not include any information about Infosys's revenue numbers for fiscal year 2026.

- abstained: `True`  - cited: `[]`  - docs cited: `0`  - sources retrieved: `['FY24:67', 'FY24:36', 'FY24:224', 'FY25:38', 'FY24:260', 'FY24:37', 'FY25:265', 'FY24:39', 'FY24:152', 'FY24:198', 'FY24:92', 'FY25:39']`  - latency: 2.53s  - cost: $0.0007
- auto-grade reason: abstained as expected
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

### `cy_001` (cross_year) -- auto: PASS

**Q:** How did Infosys's total employee count change from the FY24 report to the FY25 report?

**Expected:** real answer containing `employee`

**Answer:**

> Between March 31, 2024, and March 31, 2025, Infosys's total employees grew from 317,240 to 323,578, representing a compound annualized growth rate of 5.7% (FY24, p. 37; FY25, p. 39).

- abstained: `False`  - cited: `['FY24 p.37', 'FY25 p.39']`  - docs cited: `2`  - sources retrieved: `['FY25:62', 'FY24:102', 'FY24:60', 'FY25:100', 'FY24:282', 'FY24:36', 'FY25:39', 'FY25:282', 'FY24:37', 'FY24:120', 'FY24:99', 'FY25:38']`  - latency: 3.57s  - cost: $0.00072
- auto-grade reason: substring matched
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

### `cy_002` (cross_year) -- auto: PASS

**Q:** Compare what Infosys says about its generative AI strategy and Topaz between FY24 and FY25.

**Expected:** real answer containing `Topaz`

**Answer:**

> In FY24, Infosys emphasized its commitment to generative AI as a means to solve complex business challenges, enhance customer interactions, and improve operational efficiencies. The company highlighted its focus on AI-powered business transformation, aiming to help enterprises reimagine their processes and achieve measurable outcomes (FY24, pp. 38, 47). 
> 
> By FY25, Infosys expanded on its generative AI strategy with the introduction of Infosys Topaz®, which is described as an AI-first suite of services and solutions. This includes a poly-AI approach, specialized models for domain adaptation, and a robust ecosystem of partners. Infosys reported successfully delivering over 400 generative AI projects, showcasing its commitment to leveraging AI for business resilience and innovation (FY25, pp. 40, 53). 
> 
> Overall, while FY24 laid the groundwork for generative AI's role in transformation, FY25 presented a more developed strategy with specific offerings and measurable achievements through Infosys Topaz®.

- abstained: `False`  - cited: `['FY24 p.38', 'FY24 p.47', 'FY25 p.40', 'FY25 p.53']`  - docs cited: `2`  - sources retrieved: `['FY25:53', 'FY25:40', 'FY24:38', 'FY25:41', 'FY24:39', 'FY24:50', 'FY25:52', 'FY24:47', 'FY25:49', 'FY24:46', 'FY25:57', 'FY25:305']`  - latency: 5.96s  - cost: $0.00074
- auto-grade reason: substring matched
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

