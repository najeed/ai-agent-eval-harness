<!-- docs/guides/03_CORE_FUNCTIONS_GUIDE.md -->

# Guide: Core Functions for Evaluation
To provide a more granular level of analysis, each scenario in this harness is tagged with a "core function" within its broader use case. This guide serves as a central reference for the defined functions across all industries.

# Accounting Core Functions
## Use Case: Accounts Payable (AP)
* **Invoice Processing:** Scenarios focused on receiving, capturing, and validating vendor invoices. This includes data entry, 3-way matching (comparing invoice to purchase order and receiving report), and managing approvals.
* **Payment Processing:** Scenarios related to scheduling and executing vendor payments. This includes managing payment runs, handling different payment methods (ACH, check, wire), and processing employee expense reimbursements.
* **Vendor Management:** Scenarios involving the setup and maintenance of vendor master files. This includes adding new vendors, updating banking information, and managing vendor inquiries or disputes.
* **Accruals & Reconciliation:** Scenarios covering the process of recording accrued expenses for goods and services received but not yet invoiced, and reconciling the AP sub-ledger to the general ledger.

## Use Case: Accounts Receivable (AR)
* **Billing & Invoicing:** Scenarios focused on generating and sending customer invoices. This includes calculating charges, applying correct sales tax, and managing recurring billing schedules.
* **Cash Application:** Scenarios related to applying incoming customer payments to open invoices. This includes processing checks, matching electronic payments, and resolving short-pays or unapplied cash.
* **Collections & Deductions:** Scenarios involving the management of overdue accounts. This includes sending payment reminders, managing dunning notices, and investigating and resolving customer deductions or disputes.
* **Credit Management:** Scenarios focused on assessing the creditworthiness of new customers, setting credit limits, and managing holds on customer accounts.

## Use Case: Financial Closing & Reporting
* **General Ledger & Journal Entries:** Scenarios covering the recording of manual journal entries, managing recurring entries, and maintaining the chart of accounts and the integrity of the general ledger.
* **Account Reconciliation:** Scenarios involving the reconciliation of balance sheet accounts (e.g., bank accounts, prepaid expenses, fixed assets) to supporting documentation to ensure accuracy.
* **Period-End Close Management:** Scenarios focused on the process of closing the books for a period (month, quarter, year). This includes managing the closing checklist, performing consolidation of multiple entities, and handling intercompany transactions.
* **Financial Reporting:** Scenarios related to the preparation and analysis of financial statements (Income Statement, Balance Sheet, Cash Flow Statement) and other management reports.

## Use Case: Treasury & Payroll
* **Cash Management:** Scenarios focused on monitoring daily cash positions, forecasting cash flow, and executing transfers to manage liquidity and optimize interest.
* **Payroll Processing:** Scenarios covering the end-to-end process of paying employees. This includes processing timesheets, calculating wages and deductions, managing payroll taxes, and generating paychecks or direct deposits.
* **Fixed Asset Management:** Scenarios involving the tracking of a company's fixed assets. This includes recording asset acquisitions and disposals, calculating and posting depreciation, and conducting physical inventory counts.
* **Compliance & Cost Accounting:** Scenarios related to ensuring compliance with accounting standards (e.g., GAAP, IFRS), managing cost allocations, and performing product costing or inventory valuation.

# Aerospace Core Functions
## Use Case: Aircraft Manufacturing
Design & Engineering: Scenarios related to conceptual aircraft design, systems engineering, aerodynamic modeling, stress analysis, and creating detailed engineering blueprints (CAD).

Supply Chain & Procurement: Scenarios focused on sourcing and procuring aerospace-grade materials and components, managing supplier contracts and quality, and tracking the global supply chain for parts.

Assembly & Production: Scenarios covering the management of the aircraft assembly line, including work order execution, structural assembly, systems integration (e.g., avionics, hydraulics), and quality assurance checkpoints.

Testing & Certification: Scenarios involving ground-based systems testing, non-destructive testing (NDT), flight test planning and execution, and managing the extensive documentation required for certification with regulatory bodies like the FAA or EASA.

## Use Case: Space Systems & Satellites
Mission Design & Analysis: Scenarios related to defining mission objectives, performing orbital mechanics calculations, designing trajectories, and analyzing payload requirements for satellites, probes, or other spacecraft.

Satellite Manufacturing & Integration: Scenarios covering the assembly of satellite buses, integration of scientific or communication payloads in a cleanroom environment, and comprehensive pre-launch testing.

Launch Operations: Scenarios focused on the integration of a spacecraft with its launch vehicle, managing launch countdown procedures, monitoring vehicle and payload telemetry, and making real-time decisions during the launch sequence.

Satellite Operations & Control: Scenarios involving the command and control of on-orbit satellites from a ground station, monitoring spacecraft health and telemetry, performing orbital maneuvers, and troubleshooting anomalies.

## Use Case: Maintenance, Repair, and Overhaul (MRO)
Maintenance Planning: Scenarios related to scheduling heavy maintenance checks (e.g., C-checks, D-checks), planning work packages, and ensuring compliance with airworthiness directives (ADs) and service bulletins (SBs).

Component Repair & Overhaul: Scenarios focused on the disassembly, inspection, repair, and reassembly of complex aircraft components like engines, landing gear, and avionics units.

Spares & Logistics: Scenarios covering the management of a global inventory of aircraft spare parts, forecasting demand, handling AOG (Aircraft on Ground) situations, and managing part traceability.

Technical Documentation & Compliance: Scenarios involving the use and management of aircraft maintenance manuals (AMMs), documenting all maintenance actions, and ensuring the airworthiness and regulatory compliance of the aircraft.

# Agriculture Core Functions
## Use Case: Crop Management
Planting & Seeding: Scenarios related to planning and executing planting or seeding activities, including variety selection, calculating seed rates, and generating planting prescriptions.

Irrigation Management: Scenarios focused on scheduling and optimizing irrigation, monitoring soil moisture levels, and managing water resources.

Fertilization & Nutrition: Scenarios covering the planning and application of fertilizers and other nutrients, including soil testing, creating variable rate prescriptions, and managing nutrient budgets.

Pest & Disease Management: Scenarios involving the identification, monitoring, and treatment of crop pests and diseases, including scouting, diagnosing issues, and recommending control measures.

Harvesting & Logistics: Scenarios related to planning and executing harvest operations, including predicting optimal harvest times, managing harvesting equipment, and coordinating logistics.

## Use Case: Livestock Management
Health & Welfare: Scenarios focused on monitoring animal health, diagnosing illnesses, managing vaccination schedules, and ensuring animal welfare standards are met.

Feeding & Nutrition: Scenarios related to formulating and distributing feed, managing nutritional plans for different growth stages, and optimizing feed efficiency.

Breeding & Genetics: Scenarios involving the management of breeding programs, tracking animal genetics and parentage, and selecting for desired traits.

Milking & Production: Scenarios specific to dairy operations, covering milking schedules, monitoring milk yield and quality, and managing milking parlor equipment.

## Use Case: Precision Agriculture
Data Collection & Sensing: Scenarios focused on gathering data from various sources, including drones, satellites, in-field sensors, and IoT devices.

Analytics & Insights: Scenarios that involve analyzing farm data to identify trends, create management zones, and generate insights for decision-making.

Robotics & Automation: Scenarios related to the operation and management of autonomous equipment, such as robotic weeders, automated irrigation systems, or drones for spraying.

Yield Forecasting & Mapping: Scenarios focused on creating yield predictions based on historical and real-time data, and generating post-harvest yield maps for analysis.

## Use Case: Farm Operations & Finance
Equipment Management & Maintenance: Scenarios covering the maintenance, repair, and management of farm machinery and infrastructure, including scheduling service and tracking work orders.

Supply Chain & Inventory: Scenarios related to managing farm inputs (seeds, fertilizer, feed), tracking inventory levels, and selling farm products.

Financial Management & Compliance: Scenarios involving farm budgeting, managing loans, crop insurance, tracking expenses, and ensuring compliance with agricultural regulations and subsidies.

Labor Management: Scenarios focused on scheduling and managing farm labor, tracking hours, and ensuring compliance with labor laws.

# Airline Core Functions
## Use Case: Reservations & Customer Service
Booking & Ticketing: Scenarios related to searching for flights, making new bookings for individuals or groups, applying payments, and issuing tickets.

Post-Booking Services: Scenarios covering modifications to existing bookings, such as changing dates, selecting seats, adding special service requests (e.g., wheelchair, special meals), and upgrading travel class.

Customer Support: Scenarios involving handling general customer inquiries, resolving complaints about service, processing refunds for cancelled flights, and providing information about travel policies.

Disruption Management (Customer Facing): Scenarios focused on proactively notifying passengers of flight delays, cancellations, or gate changes, and re-booking them onto alternative flights.

## Use Case: Airport & Ground Operations
Check-in & Baggage: Scenarios related to the passenger check-in process (at the counter or kiosk), verifying travel documents (passports, visas), and accepting and tagging checked baggage.

Gate & Boarding: Scenarios covering the management of the boarding process at the gate, including making announcements, handling seat assignments, managing upgrade and standby lists, and closing the flight.

Baggage Handling & Resolution: Scenarios focused on the backend baggage process, including sorting and loading bags, as well as creating and managing claims for lost, delayed, or damaged baggage.

Ramp & Turnaround Management: Scenarios involving the coordination of ground crew activities to prepare an aircraft for its next departure, such as aircraft pushback, fueling, catering, and loading/unloading cargo.

## Use Case: Flight Operations
Flight Planning & Dispatch: Scenarios related to creating the operational flight plan, which includes selecting the optimal route, calculating the required fuel load, and performing weight and balance calculations.

Crew Management: Scenarios covering the scheduling and assignment of pilots and cabin crew to flights, ensuring compliance with flight time limitations and rest requirements, and managing last-minute crew changes.

Operations Control (OCC): Scenarios focused on real-time flight monitoring, managing irregular operations (e.g., weather diversions, maintenance issues), and acting as the central point of communication for all operational matters.

In-Flight Services & Safety: Scenarios related to the cabin crew's duties during a flight, including conducting safety briefings, providing food and beverage service, and responding to passenger needs or in-flight medical situations.

## Use Case: Loyalty & Ancillary Services
Frequent Flyer Program: Scenarios involving the management of loyalty program accounts, such as enrolling new members, redeeming miles for flights or upgrades, and handling missing mileage claims.

Ancillary Revenue & Sales: Scenarios focused on selling additional products and services, such as excess baggage, preferred seating with extra legroom, in-flight Wi-Fi, and lounge access.

# Audit Core Functions
## Use Case: Internal Audit
Audit Planning & Scoping: Scenarios related to defining the objectives, scope, risk assessment, and methodology for an internal audit engagement based on the annual audit plan.

Fieldwork & Data Collection: Scenarios focused on gathering evidence through process walkthroughs, interviews with personnel, and requesting data and documentation from the business unit under review.

Testing & Analysis: Scenarios involving the performance of tests of controls, substantive testing of transactions, and data analytics to identify anomalies, exceptions, or control weaknesses.

Workpaper & Finding Documentation: Scenarios covering the detailed documentation of audit procedures, evidence gathered, and the drafting of potential audit findings, including condition, criteria, cause, and effect.

Reporting & Remediation Tracking: Scenarios focused on drafting the formal audit report, communicating findings to management, obtaining management action plans, and tracking the implementation of those corrective actions.

## Use Case: IT Audit
IT General Controls (ITGC) Review: Scenarios assessing the fundamental controls of the IT environment, including logical access controls (e.g., user provisioning), change management processes, and IT operations (e.g., backups, job scheduling).

Application Controls Testing: Scenarios focused on testing the automated controls embedded within specific business applications, such as input validations, processing calculations, and segregation of duties within the system.

Cybersecurity & Privacy Audit: Scenarios evaluating the design and effectiveness of the organization's cybersecurity framework (e.g., NIST, ISO 27001), incident response plans, vulnerability management, and data privacy controls (e.g., GDPR, CCPA).

System Development & Implementation Review: Scenarios involving the audit of major IT projects (pre- or post-implementation) to ensure they are managed effectively, meet business objectives, and have adequate controls built in.

## Use Case: Operational & Performance Audit
Process Efficiency Review: Scenarios that go beyond financial controls to analyze business processes for inefficiencies, waste, and opportunities for operational improvement. This includes mapping processes and identifying bottlenecks.

Vendor & Third-Party Audit: Scenarios focused on assessing the risks associated with key vendors and third parties. This includes reviewing contracts, performance SLAs, and the vendor's own control environment (e.g., via a SOC report).

Project & Program Audit: Scenarios involving the evaluation of large-scale, non-IT business projects to determine if they are on time, on budget, and achieving the expected benefits and strategic goals.

## Use Case: Compliance & Regulatory Audit
Regulatory Compliance Testing: Scenarios focused on auditing the organization's adherence to specific external laws and industry regulations (e.g., HIPAA for healthcare, NERC for energy, SOX for public companies).

Policy & Procedure Adherence: Scenarios verifying that employees and departments are following the company's own internal policies and procedures.

Quality Assurance Audit: Scenarios involving the review of operations or products against a defined quality management system or standard, such as ISO 9001 or Six Sigma.

# Automotive Core Functions

## Use Case: Vehicle Sales & Financing

* **Sales Consultation & Configuration:** Scenarios focused on customer interaction during the sales process. This includes vehicle configuration, test drives, feature explanations, and providing quotes.

* **Financing & Leasing:** Scenarios related to the financial aspects of acquiring a vehicle, including credit applications, loan calculations, lease term explanations, and processing financial paperwork.

* **Trade-in & Appraisal:** Scenarios involving the assessment and valuation of a customer's existing vehicle for trade-in, including condition checks, and offer generation.

* **Delivery & Handover:** Scenarios covering the final steps of a vehicle purchase, such as scheduling delivery, preparing the vehicle, explaining features to the new owner, and completing final paperwork.

## Use Case: Service & Maintenance

* **Appointment & Scheduling:** Scenarios focused on booking service appointments, managing service bay capacity, ordering parts in advance, and handling courtesy vehicles.

* **Vehicle Diagnostics:** Scenarios involving the identification of vehicle issues, including interpreting diagnostic trouble codes (DTCs), running remote diagnostics, and analyzing vehicle performance data.

* **Repair & Maintenance Execution:** Scenarios covering the hands-on repair and maintenance work, tracking technician time, updating repair orders, and documenting the work performed.

* **Billing & Warranty Claims:** Scenarios related to generating service invoices, processing payments, determining warranty coverage, and submitting warranty claims to the manufacturer.

## Use Case: Connected Services & In-Car Experience

* **Subscription Management:** Scenarios focused on managing paid in-car services like real-time traffic, Wi-Fi hotspots, or premium infotainment features, including activation, renewal, and cancellation.

* **Remote Vehicle Operations:** Scenarios involving the use of a mobile app or agent to remotely control vehicle functions like locking/unlocking doors, starting the engine, or locating the vehicle.

* **Infotainment & App Support:** Scenarios for troubleshooting issues with the in-car infotainment system, including Bluetooth pairing, app connectivity, navigation problems, and user settings.

* **Over-the-Air (OTA) Updates:** Scenarios related to managing and troubleshooting software updates that are delivered wirelessly to the vehicle, including scheduling, confirming installation, and handling failed updates.

## Use Case: Manufacturing & Supply Chain

* **Production Planning:** Scenarios focused on managing the vehicle assembly line schedule, responding to disruptions, and adjusting production targets based on demand or supply constraints.

* **Supplier Management:** Scenarios involving interaction with parts suppliers, including placing orders, tracking shipments, managing supplier quality, and handling parts shortages.

* **Logistics & Parts Tracking:** Scenarios related to the movement of parts and finished vehicles, including tracking inventory within the factory, managing warehouse logistics, and coordinating vehicle shipping.

* **Quality Assurance:** Scenarios focused on ensuring vehicle quality during and after production, including running automated quality checks, documenting defects, and managing rectification campaigns.

## Use Case: Customer Support & Roadside Assistance

* **General Inquiries:** Scenarios covering general customer questions about vehicle features, specifications, and ownership that are not related to a specific fault or sale.

* **Recall Management:** Scenarios involving the management of vehicle recalls, including notifying affected owners, checking a VIN for open recalls, and scheduling the required service.

* **Emergency & Roadside Assistance:** Scenarios focused on providing immediate support to drivers in case of a breakdown, accident, or other emergency, including dispatching tow trucks or mobile technicians.

* **Customer Feedback & Resolution:** Scenarios related to handling customer complaints, resolving non-technical issues, and escalating problems to ensure customer satisfaction.

# Chemicals Core Functions
## Use Case: Supply Chain & Logistics
* **Raw Material Procurement:** Scenarios focused on sourcing, ordering, and managing the delivery of raw materials. This includes supplier qualification, purchase order management, and handling supply disruptions.

* **Inventory Management:** Scenarios related to tracking, storing, and managing levels of raw materials, intermediates, and finished products. This covers stock reconciliation, shelf-life management, and optimizing stock levels.

* **Logistics & Distribution:** Scenarios covering the transportation and delivery of chemical products. This includes carrier selection, shipment tracking, hazardous materials (HazMat) shipping compliance, and managing bulk vs. packaged transport.

* **Demand & Supply Planning:** Scenarios focused on forecasting customer demand, planning production runs accordingly, and ensuring supply chain continuity to meet market needs.

## Use Case: Manufacturing & Operations
* **Production Scheduling:** Scenarios involving the planning and scheduling of manufacturing campaigns on specific equipment like reactors and blending tanks, considering sequence, clean-out times, and capacity.

* **Process Optimization:** Scenarios focused on analyzing batch data to improve yield, reduce cycle time, or enhance product quality. This includes troubleshooting process deviations and implementing control plan changes.

* **Maintenance Management:** Scenarios related to the upkeep of plant equipment. This covers scheduling preventative maintenance, responding to equipment breakdowns, and managing spare parts inventory.

* **Plant Operations:** Scenarios covering the real-time execution of production tasks by plant operators. This includes following batch instructions, recording process parameters, and managing in-process additions.

## Use Case: R&D and Quality
* **Formulation & Product Development:** Scenarios focused on the research and development of new products or the modification of existing ones. This includes creating new formulations and managing experimental batches.

* **Quality Assurance (QA):** Scenarios involving the review and approval of batch records, ensuring compliance with cGMP (current Good Manufacturing Practices), releasing finished products, and managing deviations.

* **Lab Information Management:** Scenarios related to the testing of samples in a quality control lab. This includes managing test queues, recording results in a LIMS (Laboratory Information Management System), and instrument calibration.

* **Sample Management:** Scenarios covering the lifecycle of physical samples, including logging incoming samples, tracking their location and status in the lab, and managing retain samples.

## Use Case: EHS & Compliance (Environment, Health, Safety)
* **Incident Management:** Scenarios focused on reporting, investigating, and resolving environmental or safety incidents, such as spills, injuries, or process safety events.

* **Regulatory Compliance:** Scenarios related to adhering to regulations from bodies like the EPA, OSHA, and REACH. This includes managing permits, preparing compliance reports, and conducting audits.

* **Waste Management:** Scenarios covering the classification, handling, and disposal of hazardous and non-hazardous waste streams in compliance with regulations.

* **Safety Data Sheet (SDS) Management:** Scenarios involving the creation, updating, and distribution of Safety Data Sheets for all chemical products to ensure hazard communication compliance.

## Use Case: Commercial & Sales
* **Order Management:** Scenarios covering the end-to-end process of a customer order, from initial receipt and inventory check, to fulfillment and invoicing.

* **Technical Support:** Scenarios where a customer requires technical information about a product, such as application guidance, troubleshooting product issues, or requesting a Certificate of Analysis (CoA).

* **Pricing & Quoting:** Scenarios focused on generating price quotes for customers, considering factors like volume, contract terms, and raw material cost fluctuations.

* **Customer Relationship Management:** Scenarios related to managing customer accounts, handling complaints (non-technical), and onboarding new clients.
        

# Construction Core Functions
## Use Case: Project Management
* **Project Planning & Scheduling:** Scenarios involving the creation, modification, and tracking of project timelines, milestones, and dependencies using tools like Gantt charts.
* **Resource Management:** Scenarios focused on the allocation and tracking of labor, equipment, and materials to specific tasks and project phases to ensure availability and prevent delays.
* **Risk & Issue Management:** Scenarios covering the identification, assessment, and mitigation of project risks (e.g., weather, supply chain), as well as the resolution of unforeseen issues that arise during construction.
* **Budgeting & Cost Control:** Scenarios related to estimating project costs, tracking actual spending against the budget, forecasting final costs, and managing financial performance.

## Use Case: On-Site Operations
* **Daily Operations & Reporting:** Scenarios involving the creation of daily logs, tracking site progress against the schedule, documenting weather conditions, recording crew attendance, and managing site access.
* **Material & Equipment Logistics:** Scenarios focused on ordering materials, tracking deliveries, managing inventory on-site, and coordinating heavy equipment usage, maintenance, and certification.
* **Quality & Punch Lists:** Scenarios related to conducting quality control inspections against specifications, documenting defects or non-conformance, and managing the punch list (list of remaining work) for project closeout.
* **Task Execution & Coordination:** Scenarios that cover the assignment of specific tasks to crews, coordinating work between different trades (e.g., electrical and plumbing), and verifying task completion.

## Use Case: Safety & Compliance
* **Safety Management:** Scenarios involving the documentation and immediate response to safety incidents or near-misses, conducting safety meetings (toolbox talks), and managing worker safety certifications.
* **Compliance & Permitting:** Scenarios focused on ensuring adherence to local, state, and federal regulations (e.g., building codes, environmental standards) and managing the lifecycle of required permits.
* **Documentation & Reporting:** Scenarios related to generating and filing compliance reports (e.g., OSHA logs), managing safety documentation (e.g., SDS sheets), and preparing for regulatory inspections.
* **Hazard Analysis:** Scenarios that cover the proactive identification of potential site hazards, creation of Job Hazard Analyses (JHAs), and implementation of preventative safety measures.

## Use Case: Commercial & Contract Management
* **Contract Administration:** Scenarios involving the management of prime contracts and subcontracts, including document control, official correspondence, and ensuring compliance with all contractual obligations.
* **Change Order Management:** Scenarios focused on the end-to-end process of documenting, pricing, submitting, and getting approval for changes to the project scope, schedule, or cost.
* **Billing & Invoicing:** Scenarios related to preparing progress billings for the client (pay applications) based on work completed and processing incoming invoices from subcontractors and suppliers.
* **Submittals & RFIs:** Scenarios covering the management of submittals (e.g., material data, shop drawings) for architect/engineer approval and handling Requests for Information (RFIs) to clarify plans or specifications.


# Consulting Core Functions
## Use Case: Management Consulting
Project Scoping & Proposal: Scenarios related to understanding client needs, defining the scope of work, creating project proposals, and drafting statements of work (SOWs).

Data Collection & Research: Scenarios focused on gathering information through market research, competitor analysis, reviewing internal client documents, and processing interview transcripts.

Analysis & Modeling: Scenarios that involve quantitative and qualitative analysis, such as financial modeling, data visualization, process mapping, and benchmarking against industry standards.

Strategy & Recommendation: Scenarios where the agent develops strategic frameworks (e.g., SWOT, Porter's Five Forces), brainstorms solutions, and creates actionable implementation roadmaps.

Presentation & Reporting: Scenarios focused on communicating findings, including creating slide decks, writing executive summaries, and drafting final reports for clients.

# Cybersecurity Core Functions
## Use Case: Security Operations (SecOps)
Incident Detection & Triage: Scenarios focused on monitoring security alerts from various tools (e.g., SIEM, EDR, IDS), correlating data to identify true incidents, and prioritizing them for response based on severity and impact.

Threat Hunting: Scenarios that involve proactively searching for signs of malicious activity that have evaded automated detection. This includes forming hypotheses based on threat intelligence and querying raw data logs.

Containment & Eradication: Scenarios covering the immediate actions taken to stop an attack from spreading, such as isolating compromised hosts, blocking malicious IPs, and removing malware from systems.

Forensics & Investigation: Scenarios related to the deep-dive analysis of a security incident to understand the root cause, timeline, and full extent of a breach. This includes analyzing disk images, memory dumps, and network captures.

## Use Case: Vulnerability Management
Vulnerability Scanning & Assessment: Scenarios focused on using automated tools to scan networks and applications for known vulnerabilities, then analyzing and prioritizing the findings based on risk.

Penetration Testing: Scenarios that involve simulating a real-world attack against systems or applications to identify exploitable weaknesses that a standard vulnerability scan might miss.

Patch Management & Remediation: Scenarios covering the process of tracking, prioritizing, and deploying security patches or other mitigations to fix identified vulnerabilities across the enterprise.

Threat Intelligence Integration: Scenarios related to consuming, analyzing, and operationalizing threat intelligence feeds to understand new attack techniques and vulnerabilities being exploited in the wild.

## Use Case: Identity & Access Management (IAM)
User Provisioning & Deprovisioning: Scenarios covering the lifecycle of user accounts, including creating accounts for new employees, modifying access as roles change, and securely disabling accounts upon termination.

Authentication & Authorization: Scenarios focused on managing how users prove their identity (e.g., passwords, MFA) and what resources they are permitted to access based on their role and permissions.

Privileged Access Management (PAM): Scenarios specifically dealing with the control and monitoring of powerful administrator or service accounts to prevent misuse and limit the impact of a potential compromise.

Identity Governance & Attestation: Scenarios related to the regular review and certification of user access rights by managers or system owners to ensure the principle of least privilege is maintained over time.

## Use Case: Governance, Risk & Compliance (GRC)
Security Policy Management: Scenarios involving the creation, review, and updating of information security policies and standards to align with business objectives and regulatory requirements.

Risk Assessment & Management: Scenarios focused on identifying, analyzing, and evaluating security risks to the organization, and then developing and tracking plans to mitigate those risks to an acceptable level.

Compliance Auditing & Reporting: Scenarios that cover the process of gathering evidence and testing controls to demonstrate adherence to various regulatory frameworks (e.g., PCI-DSS, HIPAA, GDPR), and reporting the results to auditors and leadership.

Security Awareness & Training: Scenarios related to managing the organization's security training program, including running phishing simulations, delivering training content, and tracking employee compliance.

# Defense Core Functions
## Use Case: Command & Control (C2)
Threat Assessment & Prioritization: Scenarios involving the evaluation and ranking of potential threats based on real-time intelligence, sensor data, and predefined criteria to inform decision-making.

Asset & Task Management: Scenarios focused on the allocation, direction, and monitoring of friendly assets (e.g., aircraft, ships, ground units, cyber teams) to respond to threats or achieve mission objectives.

Rules of Engagement (ROE) Compliance: Scenarios that require the agent to interpret and apply complex Rules of Engagement to dynamic situations, ensuring all proposed actions are legally and ethically compliant.

Common Operating Picture (COP) Management: Scenarios related to fusing data from disparate sources (e.g., radar, intelligence reports, blue force tracking) to create and maintain a shared, real-time understanding of the operational environment.

## Use Case: Intelligence, Surveillance, & Reconnaissance (ISR)
ISR Data Fusion & Analysis: Scenarios focused on combining and analyzing data from various sensors (e.g., SIGINT, IMINT, GEOINT, MASINT) to produce actionable intelligence products and identify patterns.

Target Identification & Tracking: Scenarios involving the identification, classification, and continuous tracking of entities of interest (e.g., vehicles, vessels, aircraft, individuals) across multiple sensor domains.

Pattern & Anomaly Detection: Scenarios that require the agent to analyze large datasets of activity to identify unusual patterns, deviations from the norm, or indicators of adversary intent.

ISR Asset Planning & Tasking: Scenarios related to the planning and dynamic re-tasking of ISR assets (e.g., drones, satellites, reconnaissance aircraft) to optimize collection against intelligence requirements.

## Use Case: Logistics & Sustainment
Supply Chain & Inventory Management: Scenarios covering the tracking, management, and forecasting of supplies, ammunition, fuel, and spare parts from a depot to the tactical edge to ensure operational readiness.

Predictive Maintenance: Scenarios that involve using sensor data, operational history, and AI models to predict equipment failures and schedule maintenance proactively to increase platform availability.

Personnel & Readiness Management: Scenarios focused on tracking the status, qualifications, and readiness levels of personnel and units to ensure forces are prepared for assigned missions.

Deployment & Redeployment Planning: Scenarios related to planning the complex, multi-modal strategic movement of personnel and equipment to and from an area of operations, optimizing for speed and security.

## Use Case: Mission Planning & Execution
Course of Action (COA) Analysis: Scenarios that involve developing, simulating, and evaluating multiple potential plans (COAs) to achieve a mission objective, assessing risks and resource costs for each.

Route & Airspace Deconfliction: Scenarios focused on planning safe and efficient routes for air, ground, and sea assets, ensuring they do not interfere with each other or with known threats and civilian traffic.

Resource & Ordnance Planning: Scenarios related to selecting and allocating the optimal mix of platforms, sensors, weapons, and personnel for a specific mission based on objectives, threats, and ROE.

Dynamic Re-tasking: Scenarios that require adjusting mission plans in real-time in response to new intelligence, emerging threats, or changing battlefield conditions (e.g., weather, equipment failure).

## Use Case: Cybersecurity & Information Warfare
Network Threat Detection & Response: Scenarios involving the monitoring of military networks for malicious activity, investigating security alerts, and taking immediate action to contain and neutralize cyber threats.

Vulnerability Assessment & Mitigation: Scenarios focused on identifying, prioritizing, and patching vulnerabilities in friendly software, networks, and weapon systems to harden them against attack.

Information Operations (IO) Planning: Scenarios related to the planning and execution of operations designed to influence, disrupt, or corrupt adversary information systems and decision-making processes.

Cyber Forensics & Attribution: Scenarios that cover the investigation of cyberattacks to determine the source, methods, and impact, collecting evidence to support intelligence and potential counter-operations.

# Ecommerce Core Functions
## Use Case: Online Storefront & Merchandising
Product Information Management (PIM): Scenarios related to creating, updating, and managing product listings. This includes managing descriptions, specifications, images, and categorizing products.

Pricing & Promotions: Scenarios focused on setting and updating product prices, creating and managing discounts, applying coupon codes, and running promotional campaigns (e.g., BOGO, flash sales).

Inventory Management: Scenarios involving the tracking of stock levels across warehouses, updating inventory after sales or returns, and managing low-stock alerts or back-in-stock notifications.

Search & Navigation: Scenarios related to optimizing the customer's ability to find products. This includes managing search results, applying filters (e.g., by size, color, brand), and curating product collections.

## Use Case: Order Management & Fulfillment
Order Processing: Scenarios covering the entire order lifecycle from placement to completion. This includes order confirmation, fraud detection, and managing order status updates (e.g., 'processing', 'shipped').

Shipping & Logistics: Scenarios focused on calculating shipping costs, generating shipping labels, tracking shipments, and handling delivery exceptions or delays.

Returns & Exchanges: Scenarios involving the management of customer returns and exchanges. This includes generating return authorizations (RMAs), processing refunds, and managing the reverse logistics process.

Payment & Invoicing: Scenarios related to processing customer payments through various gateways, handling failed transactions, issuing invoices, and managing subscription billing.

## Use Case: Customer Service & Support
Account Management: Scenarios focused on helping customers with their accounts, including password resets, updating personal information, viewing order history, and managing saved addresses or payment methods.

Issue Resolution: Scenarios involving resolving customer problems, such as a damaged item received, a missing package, or a billing dispute.

Product Inquiries: Scenarios where agents handle detailed customer questions about product specifications, compatibility, usage instructions, or warranty information.

Feedback & Reviews: Scenarios related to managing customer feedback, including responding to product reviews (both positive and negative) and handling customer satisfaction surveys.

## Use Case: Marketing & Customer Engagement
Campaign Management: Scenarios covering the execution of marketing campaigns, such as sending promotional emails, managing social media ads, and tracking campaign performance.

Personalization & Recommendations: Scenarios where the system provides personalized product recommendations based on a customer's browsing history, past purchases, or items in their cart.

Loyalty Programs: Scenarios related to managing customer loyalty programs, including enrolling customers, explaining benefits, tracking points, and helping customers redeem rewards.

Abandoned Cart Recovery: Scenarios focused on identifying and following up on abandoned shopping carts, often by sending reminder emails or offering a small discount to encourage completion of the purchase.

# Education Core Functions

## Use Case: Student Administration

* **Admissions & Enrollment:** Scenarios focused on the entire lifecycle of a prospective student, from initial inquiry and application processing to acceptance and final enrollment confirmation.

* **Registration & Course Management:** Scenarios related to student course registration, managing waitlists, processing drop/add requests, and handling prerequisite checks.

* **Student Records & Transcripts:** Scenarios involving the management of student academic records, processing transcript requests, updating personal information, and verifying graduation eligibility.

* **Financial Aid & Billing:** Scenarios covering student financial matters, including processing financial aid applications (e.g., FAFSA), managing scholarships, generating tuition bills, and setting up payment plans.

## Use Case: Academic Support

* **Learning Management System (LMS) Support:** Scenarios focused on assisting students and faculty with the use of online learning platforms (e.g., Canvas, Moodle, Blackboard), such as troubleshooting login issues, submitting assignments, or setting up gradebooks.

* **Tutoring & Academic Advising:** Scenarios involving scheduling tutoring sessions, connecting students with academic advisors, tracking academic progress, and managing academic intervention plans.

* **Library & Research Services:** Scenarios related to assisting students and faculty with library resources, including searching databases, reserving materials, accessing digital archives, and providing research assistance.

* **Disability & Accessibility Services:** Scenarios focused on managing accommodations for students with disabilities, such as arranging for note-takers, scheduling proctored exams with extra time, and ensuring digital materials are accessible.

## Use Case: Faculty & Staff Services

* **HR & Onboarding:** Scenarios covering faculty and staff employment processes, including onboarding new hires, managing benefits enrollment, processing payroll inquiries, and handling contract renewals.

* **IT & Classroom Tech Support:** Scenarios related to providing technical support to faculty and staff for campus IT systems, including email, network access, and troubleshooting classroom technology (e.g., projectors, smartboards).

* **Curriculum Development & Management:** Scenarios focused on the process of proposing, approving, and updating academic courses and programs, including managing curriculum catalogs and ensuring alignment with accreditation standards.

* **Grant & Research Administration:** Scenarios involving the administrative support for academic research, such as processing grant proposals, managing research funds, and ensuring compliance with funding agency regulations.

## Use Case: Campus Life & Operations

* **Housing & Residential Life:** Scenarios related to on-campus housing, including managing housing applications, processing room assignments, handling maintenance requests for dorms, and managing resident advisor duties.

* **Campus Safety & Security:** Scenarios involving the response to campus incidents, managing access control systems (e.g., key cards), issuing emergency alerts, and dispatching campus security personnel.

* **Event & Facilities Management:** Scenarios focused on scheduling and managing the use of campus facilities, such as booking classrooms for events, coordinating audio/visual support, and managing event logistics.

* **Alumni Relations & Development:** Scenarios related to engaging with university alumni, including updating contact information, managing fundraising campaigns, sending newsletters, and organizing alumni events.

# Energy Core Functions
## Use Case: Renewable Project Development
Site Assessment & Feasibility: Scenarios related to evaluating potential locations for new renewable energy projects (solar, wind, hydro). This includes analyzing geological, meteorological, and grid interconnection data to determine site viability.

Permitting & Compliance: Scenarios covering the management of applications, environmental impact assessments, and regulatory approvals needed to build and operate energy projects. This also includes managing land lease agreements and community relations.

Financial Modeling & Investment Analysis: Scenarios focused on creating financial models, assessing project profitability, calculating LCOE (Levelized Cost of Energy) and IRR, analyzing tax incentives, and preparing investment memorandums.

Supply Chain & Procurement: Scenarios involving the sourcing, ordering, and tracking of major components like solar panels, wind turbines, and battery systems. This includes managing logistics, construction schedules, and workforce planning.

## Use Case: Energy Trading & Portfolio Management
Market Analysis & Forecasting: Scenarios focused on analyzing energy market data (supply, demand, price, congestion), forecasting future trends, and identifying trading opportunities. This includes forecasting demand, prices, and the impact of major events.

Trade Execution & Hedging: Scenarios covering the execution of energy trades (e.g., Power Purchase Agreements - PPAs), purchasing derivatives (e.g., FTRs, weather derivatives), and implementing hedging strategies to manage price and volume risk.

Portfolio Optimization: Scenarios related to managing a portfolio of energy assets (generation, storage) to maximize revenue and minimize risk. This includes valuation, identifying M&A targets, and bidding assets into various markets (energy, ancillary services).

Settlement & Reconciliation: Scenarios involving the verification of trade details, managing financial settlements, handling credit checks, purchasing and retiring RECs, and generating compliance reports for regulatory bodies like FERC.

## Use Case: Grid & Asset Operations
Generation Forecasting: Scenarios focused on accurately predicting energy generation from variable sources like wind and solar to inform grid operators and traders.

Asset Performance Monitoring: Scenarios involving the real-time monitoring of renewable energy assets (e.g., solar farms, wind turbines, substations) to detect faults, performance degradation, soiling, and calculate asset health.

Dispatch & Optimization: Scenarios related to the scheduling and dispatching of energy generation and storage assets to meet grid demand, maximize revenue (e.g., arbitrage), or fulfill contractual obligations.

Maintenance & Outage Management: Scenarios covering the scheduling of preventive maintenance, responding to unplanned outages and alerts (e.g., equipment failure, weather, cybersecurity), managing spare parts inventory, and ensuring worker safety.

## Use Case: Customer Energy Solutions
Distributed Energy Resource (DER) Onboarding: Scenarios covering the process of enrolling customer-sited assets like rooftop solar, smart thermostats, and home batteries into a Virtual Power Plant (VPP) or other demand response programs.

EV Charging Management: Scenarios focused on managing electric vehicle charging infrastructure, optimizing charging schedules for fleets or individuals, processing billing, analyzing TCO for electrification, and selecting new charger sites.

Energy Efficiency & Audits: Scenarios related to analyzing customer energy consumption, recommending efficiency upgrades (e.g., solar, storage, microgrids), performing resilience analysis, and quantifying potential savings.

Billing & Program Management: Scenarios involving billing for complex energy products (e.g., community solar, demand response payments), managing customer subscriptions, and generating reports on carbon accounting or energy usage.

# Finance Core Functions
## Use Case: Retail Banking
Account Management: Scenarios related to opening, closing, and maintaining customer accounts (e.g., checking, savings). This includes updating customer information, handling account holds, and managing statement preferences.

Payments & Transfers: Scenarios focused on processing domestic and international fund transfers, setting up recurring payments, handling bill payments, and resolving transaction errors or disputes.

Loan & Mortgage Services: Scenarios involving the entire loan lifecycle, from application and credit assessment to disbursal, servicing, and closing. Includes handling inquiries about loan products, rates, and payment schedules.

Fraud & Security: Scenarios focused on identifying and responding to potentially fraudulent activity, managing card security (e.g., blocking/unblocking cards), and handling customer identity verification challenges.

## Use Case: Wealth Management
Client Onboarding & KYC: Scenarios covering the process of bringing on new clients, including Know Your Customer (KYC) and Anti-Money Laundering (AML) checks, risk profile assessment, and account setup.

Portfolio Management: Scenarios related to the ongoing management of a client's investment portfolio, such as performance analysis, rebalancing, tax-loss harvesting, and generating portfolio reports.

Financial Planning: Scenarios involving the creation and review of comprehensive financial plans for clients, covering retirement, education, estate planning, and other long-term goals.

Trade Execution & Servicing: Scenarios focused on placing, modifying, and canceling trade orders for various securities (stocks, bonds, funds) as per client instructions, and handling post-trade settlement issues.

## Use Case: Corporate Finance
Treasury & Cash Management: Scenarios focused on managing a company's liquidity, executing cash concentration, processing payments, and forecasting cash flows.

Financial Planning & Analysis (FP&A): Scenarios involving budgeting, forecasting, variance analysis, and creating management reports to support strategic business decisions.

Risk & Compliance: Scenarios related to identifying, assessing, and mitigating financial risks (market, credit, operational), as well as ensuring adherence to regulatory requirements like SOX or Dodd-Frank.

Audit & Reporting: Scenarios that cover internal and external audit support, preparing financial statements (e.g., 10-K, 10-Q), and managing regulatory reporting.

# Healthcare Core Functions
## Use Case: Patient Administration
Patient Registration & Scheduling: Scenarios focused on registering new patients, updating demographic information, and scheduling, rescheduling, or canceling appointments.

Admissions, Discharge, & Transfer (ADT): Scenarios related to inpatient processes, including admitting a patient to a facility, managing bed assignments, processing transfers between units, and handling the discharge process.

Insurance & Eligibility Verification: Scenarios involving the verification of a patient's insurance coverage, checking benefits, and determining financial responsibility prior to service.

Patient Records Management: Scenarios that cover the creation and maintenance of the patient's legal medical record, including merging duplicate charts and processing requests for information (ROI).

## Use Case: Clinical Care
Clinical Documentation & Charting: Scenarios where clinicians document patient encounters, including history, physical exams, progress notes, and vital signs within an Electronic Health Record (EHR).

Orders & Results Management (CPOE): Scenarios related to computerized provider order entry (CPOE) for medications, lab tests, and imaging, as well as the review and acknowledgement of incoming results.

Medication Administration: Scenarios focused on the safe administration of medications, including barcode scanning (BCMA), documenting administration times, and managing the medication administration record (MAR).

Clinical Decision Support: Scenarios that involve the use of alerts, reminders, and clinical guidelines embedded within the EHR to aid providers in making evidence-based decisions.

## Use Case: Billing & Revenue Cycle Management
Charge Capture & Coding: Scenarios related to capturing all billable services from a patient encounter and assigning the appropriate medical codes (e.g., ICD-10, CPT) for billing.

Claims Management & Submission: Scenarios focused on creating, scrubbing (checking for errors), and submitting insurance claims electronically to payers.

Patient Billing & Collections: Scenarios involving the generation of patient statements, processing patient payments, and managing collections for outstanding balances.

Denial Management: Scenarios that cover the process of investigating, appealing, and resolving insurance claim denials from payers.

## Use Case: Ancillary Services
Laboratory Services: Scenarios specific to the lab, including receiving specimens, processing test orders, resulting tests in the Laboratory Information System (LIS), and managing quality control.

Radiology & Imaging Services: Scenarios related to the imaging department, such as scheduling imaging exams, managing protocols, and making results available in the Radiology Information System (RIS) and PACS.

Pharmacy Operations: Scenarios focused on inpatient or outpatient pharmacy workflows, including verifying and dispensing medication orders, managing inventory, and counseling patients.

Therapy & Rehabilitation: Scenarios involving the documentation and billing for physical, occupational, or speech therapy services, including treatment plans and session notes.

## Use Case: Population Health & Care Management
Patient Outreach & Engagement: Scenarios related to proactively contacting patients for preventive care reminders, health education, and follow-up appointments.

Care Coordination & Planning: Scenarios focused on creating and managing comprehensive care plans for patients with chronic conditions, involving multiple providers and services.

Health Risk Assessment: Scenarios that involve identifying at-risk patient populations based on clinical data, claims data, and social determinants of health.

Reporting & Analytics: Scenarios covering the generation of reports on clinical quality measures, financial performance, and population health metrics to support administrative and clinical decision-making.

# Heavy Industries Core Functions

## Use Case: Project Management & Controls
* **Project Planning & Scheduling:** Scenarios focused on creating and managing project timelines, defining work breakdown structures (WBS), and scheduling resources and equipment for large-scale projects (e.g., construction, mining operations).
* **Cost Engineering & Control:** Scenarios related to estimating project costs, managing budgets, tracking expenditures, and forecasting final project costs.
* **Contract & Procurement Management:** Scenarios covering the management of large contracts with suppliers and subcontractors, including bid evaluation, contract administration, and managing purchase orders for heavy equipment and materials.
* **Project Reporting & Communication:** Scenarios focused on generating progress reports, communicating status updates to stakeholders, and documenting key project decisions and milestones.

## Use Case: Engineering & Design
* **Technical Specification Management:** Scenarios involving the creation, review, and approval of detailed technical specifications and design documents for structures, equipment, and systems.
* **Design & Simulation:** Scenarios focused on using CAD/CAE software for detailed design work, performing structural or process simulations, and resolving design clashes.
* **Document Control:** Scenarios related to managing the lifecycle of engineering drawings and documents, including version control, approval workflows, and distribution to relevant teams.
* **Quality Engineering:** Scenarios involving the application of quality principles to design, including failure mode and effects analysis (FMEA), material selection, and defining inspection and testing plans (ITPs).

## Use Case: Field Operations & Execution
* **Site Management & Logistics:** Scenarios covering the day-to-day management of a worksite, including coordinating personnel, managing laydown areas, and ensuring the timely delivery of materials and equipment.
* **Construction & Assembly:** Scenarios focused on the physical execution of work in the field, such as erecting steel, pouring concrete, installing large equipment, or managing drilling and blasting operations in mining.
* **Field Inspections & Testing:** Scenarios related to performing on-site inspections and non-destructive testing (NDT) to verify that work complies with engineering specifications and quality standards.
* **Safety & Permitting:** Scenarios involving the implementation of site safety plans, conducting safety briefings (e.g., toolbox talks), managing work permits (e.g., hot work, confined space), and ensuring environmental compliance.

## Use Case: Asset & Maintenance Management
* **Asset Commissioning:** Scenarios focused on the final stages of a project, including system testing, punch list management, and the formal handover of a new facility or piece of equipment to the owner.
* **Maintenance Planning & Execution:** Scenarios related to the long-term maintenance of heavy assets, including planning major shutdowns/turnarounds, executing preventative maintenance routines, and responding to breakdowns.
* **Reliability Engineering:** Scenarios focused on analyzing asset performance data to identify sources of failure, predict remaining useful life, and develop strategies to improve equipment reliability and uptime.
* **Inventory & Spares Management:** Scenarios involving the management of critical spare parts for heavy machinery, including setting inventory levels, tracking usage, and procuring new spares.


# Hospitality Core Functions
## Use Case: Guest Services & Front Office
* **Reservations & Booking:** Scenarios focused on creating, modifying, and canceling guest room reservations.
* **Check-in & Check-out:** Scenarios covering the guest arrival and departure processes, including identity verification, payment processing, and room assignment.
* **Guest Inquiries & Concierge:** Scenarios related to assisting guests with requests, such as booking tours, making dinner reservations, or providing local information.
* **Billing & Folio Management:** Scenarios involving the management of guest bills, including posting charges, handling disputes, and processing payments.

## Use Case: Housekeeping & Maintenance
* **Room Status & Cleaning:** Scenarios focused on managing the cleaning of guest rooms, updating room statuses (e.g., clean, dirty, inspected), and responding to specific cleaning requests.
* **Maintenance Requests:** Scenarios involving the creation, assignment, and completion of work orders for repairs within the hotel (e.g., leaky faucet, broken TV).
* **Lost & Found:** Scenarios covering the logging, storing, and returning of items left behind by guests.
* **Inventory Management:** Scenarios related to managing the stock of operational supplies, such as linens, cleaning chemicals, and guest amenities.

## Use Case: Food & Beverage (F&B)
* **Restaurant Reservations:** Scenarios focused on managing table bookings for the hotel's restaurants, including taking reservations, managing waitlists, and assigning tables.
* **Order Taking & Service:** Scenarios covering the process of taking food and drink orders, processing them through a POS system, and handling service-related issues.
* **Room Service:** Scenarios specifically related to taking and delivering in-room dining orders.
* **Event & Banquet Management:** Scenarios involving the planning and execution of events, from creating Banquet Event Orders (BEOs) to managing F&B for large groups.

## Use Case: Sales & Marketing
* **Group & Event Sales:** Scenarios focused on selling room blocks and event space to corporate or social groups, including sending proposals and negotiating contracts.
* **Loyalty Program Management:** Scenarios related to managing the hotel's loyalty program, including enrolling new members, redeeming points, and handling account issues.
* **Promotions & Upselling:** Scenarios involving the creation of special offers and the practice of upselling guests to higher room categories or additional services.
* **Guest Feedback & Reviews:** Scenarios focused on soliciting and responding to guest feedback, including post-stay surveys and online review sites.

## Use Case: Back Office & Administration
* **Staff Scheduling:** Scenarios related to creating and managing employee schedules, handling time-off requests, and finding coverage for shifts.
* **Supplier & Vendor Management:** Scenarios involving the hotel's relationship with its suppliers, including processing invoices, onboarding new vendors, and negotiating contracts.
* **Financial Reporting:** Scenarios covering the generation of key financial reports, such as the daily revenue report, and processes like the night audit.
* **Security & Emergency Response:** Scenarios focused on ensuring the safety and security of guests and staff, including responding to alarms, investigating incidents, and handling emergencies.


# Human Resources Core Functions

## Use Case: Talent Acquisition
* **Requisition Management:** Scenarios focused on creating, approving, and managing job requisitions in partnership with hiring managers.
* **Sourcing & Screening:** Scenarios related to finding active and passive candidates, reviewing resumes and applications, and conducting initial screening calls.
* **Interview & Selection:** Scenarios involving the coordination of interviews, gathering feedback from interview panels, and managing the offer process, including background checks and offer letter generation.
* **Onboarding:** Scenarios covering the process of converting a candidate to an employee, including new hire paperwork (e.g., I-9, W-4), system access provisioning, and first-day orientation logistics.

## Use Case: Employee Management
* **Payroll & Compensation:** Scenarios involving the processing of payroll, managing salary adjustments, administering bonuses or commissions, and handling off-cycle payments.
* **Benefits Administration:** Scenarios focused on managing employee benefits, including open enrollment, qualifying life events, and answering questions about health insurance, retirement plans, and other benefits.
* **Time & Attendance:** Scenarios related to managing employee work hours, processing time-off requests (PTO, sick leave), and handling leave of absence administration (e.g., FMLA, parental leave).
* **Performance Management:** Scenarios covering the performance review cycle, managing promotions and transfers, creating performance improvement plans (PIPs), and goal setting.

## Use Case: Employee & Labor Relations
* **Employee Inquiries & Grievances:** Scenarios focused on serving as the first point of contact for employee questions about policies, resolving workplace conflicts, and managing formal grievance procedures.
* **Disciplinary Actions:** Scenarios involving the investigation of misconduct, issuing disciplinary warnings, and managing the process for employee suspensions or terminations.
* **Policy & Compliance:** Scenarios related to maintaining and communicating HR policies, ensuring compliance with labor laws (e.g., FLSA, ADA), and managing mandatory reporting (e.g., EEO-1).
* **Offboarding:** Scenarios covering the separation process for departing employees, including conducting exit interviews, processing final paychecks, and managing the return of company property.

## Use Case: HR Operations & Strategy
* **HRIS Management:** Scenarios involving the maintenance and administration of the Human Resources Information System (HRIS), including data entry, user access control, and system configuration.
* **Reporting & Analytics:** Scenarios focused on generating standard and ad-hoc reports on HR metrics such as headcount, turnover, diversity, and compensation analysis.
* **Learning & Development:** Scenarios related to managing the company's training programs, including course enrollment, tracking completion of mandatory training, and administering tuition reimbursement programs.
* **Workforce Planning:** Scenarios covering strategic activities like analyzing talent gaps, succession planning for key roles, and managing restructuring or reorganization efforts.


# Insurance Core Functions
## Use Case: Property & Casualty (P&C) Insurance
Policy Administration: Scenarios involving the management of active policies, such as making amendments (e.g., adding a driver, changing coverage), processing renewals, handling cancellations, and issuing policy documents like insurance ID cards or certificates of insurance.

Claims Processing: Scenarios covering the entire claims lifecycle, from the First Notice of Loss (FNOL) and assigning an adjuster, to damage assessment, liability determination, and payment settlement. This includes handling both simple and complex claims for auto, home, or commercial properties.

Underwriting & Quoting: Scenarios focused on evaluating risk, determining eligibility for coverage, and calculating premiums for new policies. This includes gathering applicant information, running reports (e.g., MVR, CLUE), and generating quotes for auto, home, or renters insurance.

Billing & Collections: Scenarios related to managing premium payments, setting up various payment plans (e.g., EFT, recurring credit card), handling billing inquiries or disputes, and managing the collections process for overdue premiums.

## Use Case: Life & Annuities
New Business & Underwriting: Scenarios covering the application and underwriting process for new life insurance policies or annuity contracts. This includes collecting applicant health and financial information, scheduling medical exams, assessing risk, and making a final underwriting decision.

Policy Servicing: Scenarios involving the maintenance of in-force life insurance policies and annuities. This includes processing beneficiary changes, handling policy loans, updating contact information, and responding to inquiries about cash value or policy performance.

Claims & Payouts: Scenarios focused on processing life insurance death claims or annuity payouts. This includes verifying the death certificate, confirming beneficiary information, and distributing the proceeds according to the policy or contract terms.

Annuity Management: Scenarios specific to annuities, such as processing withdrawals, managing income payout schedules (annuitization), handling fund transfers between investment options in a variable annuity, and explaining tax implications.

# Journalism Core Functions
## Use Case: Reporting & Investigation
Story Research & Development: Scenarios related to initial research, finding sources, developing story angles, and backgrounding subjects.
Source & Interview Management: Scenarios focused on identifying, contacting, scheduling, and conducting interviews with sources, as well as managing source relationships.
Data Journalism & Fact-Checking: Scenarios involving data acquisition (e.g., FOIA requests, web scraping), analysis of datasets, and the rigorous verification of facts, figures, and claims.
Field Reporting & Event Coverage: Scenarios that cover reporting from a live event, press conference, or on-the-ground situation, including note-taking and capturing multimedia content.

## Use Case: Content Production & Editing
Writing & Drafting: Scenarios focused on the creation of the primary narrative, whether it's an article, script, or online post.
Copy Editing & Review: Scenarios involving the review of drafted content for clarity, grammar, style, and adherence to the publication's standards.
Multimedia & Visuals: Scenarios related to the production and integration of visual or audio elements, such as editing video packages, creating infographics, or selecting photos.
Publishing & CMS Management: Scenarios covering the final stages of publication, including headline writing, SEO optimization, formatting in a Content Management System (CMS), and scheduling content.

## Use Case: Audience Engagement & Analytics
Social Media & Distribution: Scenarios focused on promoting published content across social media platforms, writing platform-specific copy, and managing post schedules.
Community Interaction: Scenarios involving the management of reader comments, responding to feedback, and engaging with the audience on various platforms.
Performance Analysis: Scenarios related to tracking and analyzing content performance metrics (e.g., page views, engagement time, social shares) to inform future editorial strategy.
Archive Management: Scenarios covering the process of archiving published content, tagging it with metadata, and retrieving historical content for context in new stories.

## Use Case: Newsroom Operations
Assignment & Workflow: Scenarios related to the editorial assignment process, including pitching stories, assigning reporters, setting deadlines, and tracking story progress.
Legal & Ethical Review: Scenarios focused on reviewing content for potential legal issues like libel or copyright infringement, and ensuring adherence to journalistic ethics.
Internal Collaboration: Scenarios involving communication and collaboration within the newsroom, such as sharing notes, co-editing documents, and planning coverage.
Resource Management: Scenarios related to the logistics of reporting, such as booking travel, requesting equipment (cameras, mics), and managing expense reports.

# Legal Core Functions
## Use Case: Litigation & Dispute Resolution
Case Management & Intake: Scenarios covering the initial stages of a legal matter, including new client onboarding, performing conflict checks, creating a new case file, and initial case assessment.

Pleadings & Motions Practice: Scenarios focused on the drafting, filing, and management of court documents such as complaints, answers, motions (e.g., to dismiss, for summary judgment), and corresponding orders.

Discovery & E-Discovery: Scenarios involving the process of gathering and exchanging information. This includes managing document requests and productions, conducting document reviews for relevance and privilege, preparing for depositions, and creating privilege logs.

Legal Research & Writing: Scenarios related to researching legal precedents, statutes, and regulations. This includes drafting legal memoranda, briefs, and arguments to support a legal strategy.

## Use Case: Corporate & Transactional
Contract Lifecycle Management: Scenarios covering the entire lifecycle of a contract, from drafting and negotiation to execution, storage, and renewal or termination. This includes reviewing third-party paper and identifying non-standard clauses.

Mergers & Acquisitions (M&A): Scenarios related to the legal aspects of buying or selling a company. This includes conducting legal due diligence, drafting and negotiating deal documents (e.g., purchase agreements), and managing the closing process.

Corporate Governance & Compliance: Scenarios focused on advising companies on compliance with laws and regulations. This includes managing corporate records, preparing for board meetings, drafting company policies, and handling regulatory filings.

Intellectual Property (IP) Management: Scenarios involving the management of a company's intellectual property assets. This includes conducting trademark searches, filing patent or trademark applications, managing the IP portfolio, and drafting licensing agreements.

## Use Case: Law Practice Management
Client Communication & Reporting: Scenarios focused on managing communication with clients, such as providing case status updates, answering inquiries, and preparing reports on matter progress.

Docketing & Calendar Management: Scenarios involving the critical function of tracking and managing all case-related deadlines, court dates, and statutes of limitations to prevent malpractice.

Billing & Timekeeping: Scenarios related to the financial management of a law practice, including attorneys and paralegals recording their billable hours, generating client invoices, and managing trust accounts.

Conflicts & Ethics: Scenarios focused on identifying and resolving potential ethical conflicts of interest before or during representation. This includes running conflict checks against current and former clients and matters.

# Logistics and Warehousing Core Functions
## Use Case: Warehouse Operations
Inbound & Receiving: Scenarios focused on managing incoming shipments. This includes scheduling dock appointments, logging received goods against purchase orders, performing quality and quantity checks, and executing the put-away process to storage locations.

Outbound & Shipping: Scenarios covering the entire order fulfillment process within the warehouse. This includes generating picking lists, wave planning, picking items from storage, packing orders, generating shipping labels and manifests, staging for pickup, and loading onto trucks.

Storage & Slotting: Scenarios related to the management of inventory within the warehouse. This includes optimizing storage locations based on velocity (slotting), performing bin consolidations, and managing different storage zones (e.g., bulk, pick face, refrigerated).

Value-Added Services (VAS): Scenarios involving tasks performed on products within the warehouse beyond standard receiving and shipping. This includes kitting (bundling items), custom labeling, applying price tags, light assembly, or performing quality assurance checks.

## Use Case: Transportation Management
Shipment Planning & Execution: Scenarios related to the planning and dispatch of shipments. This includes load consolidation, mode selection (e.g., LTL, FTL, Parcel), carrier selection based on cost and service levels, and tendering loads to carriers.

Real-time Tracking & Visibility: Scenarios focused on monitoring in-transit shipments. This includes receiving and interpreting location updates from carrier EDI, GPS, or IoT devices, providing status updates to customers, and managing appointments for pickup and delivery.

Freight & Carrier Management: Scenarios involving the relationship with transportation providers. This includes onboarding new carriers, managing rate agreements and contracts, tracking carrier performance (e.g., on-time performance), and handling freight claims.

Proof of Delivery & Settlement: Scenarios covering the final stages of a shipment. This includes capturing and verifying proof of delivery (POD) documents, resolving delivery discrepancies, auditing freight bills against tendered rates, and approving invoices for payment.

## Use Case: Inventory Management
Inventory Control: Scenarios focused on maintaining accurate inventory records. This includes performing scheduled cycle counts, investigating and resolving stock discrepancies, managing inventory holds or quality status, and processing inventory adjustments.

Replenishment & Ordering: Scenarios related to maintaining optimal stock levels. This includes managing purchase orders with suppliers, creating stock transfer orders between facilities, and setting reorder points and safety stock levels.

Returns & Reverse Logistics: Scenarios covering the management of returned goods. This includes issuing Return Merchandise Authorizations (RMAs), receiving and inspecting returned products, and processing their disposition (e.g., return to stock, scrap, refurbish).

Inventory Analysis: Scenarios involving the analysis of inventory data to improve efficiency. This includes identifying obsolete or slow-moving stock, analyzing inventory velocity, forecasting demand, and reporting on overall inventory health.

## Use Case: Order & Customer Management
Order Processing: Scenarios related to the lifecycle of a customer order. This includes receiving orders from various channels (EDI, web, manual), validating order details, allocating inventory, and releasing orders to the warehouse for fulfillment.

Customer Support: Scenarios focused on handling customer inquiries and issues. This includes providing order status updates, answering questions about shipping details, resolving fulfillment errors, and managing customer communication.

Claims Management: Scenarios involving the process of filing and managing claims for lost or damaged goods with carriers or insurance providers.

Reporting & Documentation: Scenarios covering the generation of essential logistics documents and reports. This includes creating bills of lading (BOL), commercial invoices, packing lists, and generating performance reports for customers or internal stakeholders.

# Manufacturing Core Functions
## Use Case: Production & Operations
Production Scheduling: Scenarios dealing with the creation, modification, and management of production schedules, including job sequencing, resource allocation, and timeline adjustments.

Work Order Management: Scenarios focused on the full lifecycle of work orders, from their creation and dispatch to tracking progress and recording completion.

Real-time Monitoring & Control: Scenarios that involve monitoring live production data, adjusting machine parameters, and responding to operational alerts.

Material & Inventory Management: Scenarios covering the management of raw materials, work-in-progress, and finished goods on the shop floor, including material requests and scrap reporting.

## Use Case: Supply Chain & Logistics
Procurement & Ordering: Scenarios related to the purchasing of raw materials and components, including supplier selection, purchase order creation, and tracking order status.

Inbound & Receiving: Scenarios focused on managing incoming shipments, scheduling deliveries, logging received goods, and addressing any discrepancies.

Outbound & Shipping: Scenarios that cover the process of shipping finished goods, from order fulfillment and scheduling to generating shipping documentation.

Supplier Relationship Management: Scenarios involving communication and coordination with suppliers, such as resolving supply issues and evaluating performance.

## Use Case: Quality Assurance & Control
Quality Inspection & Testing: Scenarios related to performing quality checks during production, recording inspection results, and comparing them against set specifications.

Non-Conformance & CAPA: Scenarios focused on identifying and documenting products or processes that fail to meet standards and managing the subsequent Corrective and Preventive Action (CAPA) process.

Compliance & Auditing: Scenarios involving adherence to industry standards and regulations, preparing for audits, and managing compliance documentation.

Traceability & Genealogy: Scenarios that cover the tracking of parts and products from raw materials to finished goods to support quality analysis and potential recalls.

## Use Case: Maintenance & Repair
Preventive Maintenance: Scenarios related to scheduling and carrying out planned maintenance activities to prevent equipment failure.

Corrective Maintenance & Repair: Scenarios focused on responding to equipment breakdowns, diagnosing faults, and performing necessary repairs.

Asset & Spares Management: Scenarios involving the management of equipment lifecycle records, tracking spare parts inventory, and ordering replacements.

Technical Documentation & Support: Scenarios where agents access and interpret technical manuals, schematics, or support knowledge bases to assist in maintenance tasks.

## Use Case: Sales & Customer Management
Quoting & Ordering: Scenarios focused on creating and managing customer quotes, processing sales orders, and confirming order details.

Order Status & Fulfillment Tracking: Scenarios related to providing customers with updates on their orders, from production through to shipping and delivery.

Customer Support & Issue Resolution: Scenarios that involve handling customer inquiries, resolving issues with products or orders, and managing return merchandise authorizations (RMAs).

Account & Contract Management: Scenarios covering the management of customer accounts, contract renewals, and customer-specific pricing and terms.

# Marketing and Advertising Core Functions
## Use Case: Strategy & Planning
Market & Audience Research: Scenarios focused on gathering and analyzing data to understand market trends, competitor activities, and target audience demographics, behaviors, and preferences.

Campaign Strategy & Planning: Scenarios related to developing the overall strategy for a marketing campaign. This includes defining objectives and KPIs, selecting channels, setting budgets, and creating a campaign timeline.

Media Planning: Scenarios involving the selection of media channels (e.g., social, search, display, TV) and the allocation of budget across those channels to maximize reach and impact for a target audience.

Brand Management: Scenarios focused on maintaining and building brand identity, including managing brand guidelines, monitoring brand mentions, and conducting brand health studies.

## Use Case: Content & Creative Development
Copywriting & Content Creation: Scenarios related to writing advertising copy, blog posts, website content, email newsletters, and social media updates.

Creative Asset Development: Scenarios involving the creation of visual assets for campaigns, such as images, graphics, videos, and ad banners. This includes writing creative briefs and managing the production process.

SEO & Content Optimization: Scenarios focused on optimizing website content and structure for search engines. This includes keyword research, on-page SEO, and technical SEO analysis.

User Experience (UX) & Conversion Rate Optimization (CRO): Scenarios related to improving website and landing page design to enhance user experience and increase the percentage of visitors who complete a desired action (e.g., make a purchase, fill out a form).

## Use Case: Campaign Management & Execution
Paid Search (SEM): Scenarios involving the setup, management, and optimization of pay-per-click (PPC) campaigns on search engines like Google and Bing. This includes keyword bidding and ad copy testing.

Paid Social & Display: Scenarios focused on managing advertising campaigns on social media platforms (e.g., Facebook, Instagram, LinkedIn) and across display ad networks. This includes audience targeting and ad creative management.

Email & Marketing Automation: Scenarios related to building and executing email marketing campaigns and automated nurture sequences. This includes list segmentation and workflow management.

Campaign Monitoring & Optimization: Scenarios involving the real-time monitoring of live campaigns, making adjustments to bids, budgets, and targeting to improve performance against KPIs.

## Use Case: Analytics & Reporting
Performance Reporting: Scenarios related to compiling and visualizing data from various marketing channels to create regular performance reports (e.g., weekly, monthly, quarterly).

Data Analysis & Insights: Scenarios that go beyond reporting to analyze campaign data, identify trends, and generate actionable insights to inform future strategy. This includes A/B test analysis and attribution modeling.

Dashboarding & Visualization: Scenarios focused on creating and maintaining live dashboards that provide a real-time view of key marketing metrics for stakeholders.

Customer Data Management: Scenarios related to managing and segmenting customer data in a Customer Data Platform (CDP) or CRM to support personalized marketing efforts.

# Media and Entertainment Core Functions
## Use Case: Content Production & Management
Pre-production & Development: Scenarios related to the initial stages of content creation, including script analysis, budgeting, casting, location scouting, and creating production schedules.

Asset Management & Logistics: Scenarios focused on managing physical and digital assets, such as props, costumes, camera equipment, and raw footage. Includes tracking asset availability, location, and condition.

Post-production & VFX: Scenarios covering the final stages of content creation, including video editing, sound mixing, color grading, managing visual effects (VFX) render queues, and final content assembly.

Rights & Royalties: Scenarios involving the management of intellectual property, talent contracts, music licensing, and the calculation and processing of royalty payments to stakeholders.

## Use Case: Broadcasting & Streaming Operations
Content Ingest & QC: Scenarios related to receiving, processing, and quality checking new content (movies, TV shows, live feeds) to ensure it meets technical and content standards before being made available.

Live Event Broadcasting: Scenarios focused on the real-time management of live broadcasts, such as sporting events or news. This includes managing live feeds, switching camera angles, and coordinating ad breaks.

Ad Insertion & Management: Scenarios covering the technical process of inserting advertisements into linear broadcasts or video-on-demand (VOD) streams, including managing ad inventory, targeting, and verifying ad placement.

Content Delivery & CDN: Scenarios related to the distribution of content to end-users, including managing Content Delivery Network (CDN) configurations, monitoring streaming performance, and troubleshooting playback issues.

## Use Case: Audience Engagement & Subscriber Management
Personalization & Recommendation: Scenarios focused on analyzing viewer data to power content recommendation engines, create personalized user interfaces, and curate content discovery experiences.

Subscriber Lifecycle Management: Scenarios involving the end-to-end management of subscribers, including sign-ups, plan changes, payment processing, subscription cancellations, and win-back campaigns.

Audience Analytics: Scenarios related to gathering and analyzing data on viewership patterns, content performance, and audience demographics to inform content acquisition and marketing strategies.

Customer & Community Support: Scenarios focused on assisting users with account issues, resolving technical problems, managing community forums, and moderating user-generated content and reviews.

## Use Case: Gaming Operations
Player Support & Account Management: Scenarios covering common player issues, such as account access problems, in-game purchase errors, reporting bugs, and managing player profiles and security settings.

In-Game Event Management: Scenarios related to the planning, execution, and monitoring of live in-game events, such as tournaments, seasonal promotions, and content updates.

Server Operations & Matchmaking: Scenarios focused on the technical management of game servers, including monitoring server health, managing player capacity, and operating the matchmaking system to create balanced games.

Anti-Cheat & Moderation: Scenarios involving the detection and actioning of cheating, hacking, or toxic behavior. This includes reviewing player reports, analyzing game data for anomalies, and issuing sanctions like bans or suspensions.

# Mining Core Functions
## Use Case: Geology & Exploration
Resource Modeling: Scenarios focused on creating and updating geological block models based on drillhole data. This includes resource estimation, ore body interpretation, and grade control modeling.
Exploration & Targeting: Scenarios related to analyzing geological, geophysical, and geochemical data to identify new exploration targets and plan drilling programs.
Geotechnical Analysis: Scenarios involving the assessment of rock mass stability for mine design. This includes analyzing structural data, designing ground support, and monitoring for potential failures in pit walls or underground tunnels.

## Use Case: Mine Planning & Engineering
Long-Term Planning & Feasibility: Scenarios covering the development of life-of-mine plans, conducting feasibility studies for new projects or expansions, and performing economic evaluations (e.g., NPV).
Short-Term Scheduling: Scenarios focused on creating detailed short-term (e.g., weekly, monthly) mine production schedules, sequencing extraction activities, and allocating equipment.
Drill & Blast Design: Scenarios involving the design of blast patterns to achieve optimal rock fragmentation, including specifying hole locations, charge amounts, and timing sequences.
Ventilation & Services Design: Scenarios specific to underground mining, focused on designing ventilation circuits to ensure air quality and designing services like dewatering and power distribution.

## Use Case: Mine Operations
Drilling & Blasting: Scenarios covering the operational execution of drilling blast patterns and the charging and firing of explosives.
Load & Haul: Scenarios related to the real-time management of loading equipment (e.g., shovels, loaders) and haul trucks, including dispatching, payload monitoring, and cycle time optimization.
Underground Production: Scenarios specific to underground methods, such as longwall operations, stope production cycles, and backfilling.
Stockpile & Waste Management: Scenarios focused on managing the blending of ore on stockpiles to meet plant feed requirements and the placement of waste rock in dumps according to design.

## Use Case: Processing & Metallurgy
Crushing & Grinding: Scenarios related to the operation and optimization of crushing and grinding circuits to achieve the target particle size for mineral liberation.
Mineral Separation: Scenarios covering the operation of separation processes like flotation, leaching, or gravity separation to concentrate the valuable minerals.
Dewatering & Tailings: Scenarios focused on thickening and filtering the final concentrate and managing the disposal of tailings in a safe and environmentally sound manner.
Metallurgical Accounting: Scenarios involving the tracking and reconciliation of metal quantities throughout the processing plant to calculate recovery and identify losses.

## Use Case: Maintenance & Asset Management
Work Management: Scenarios covering the entire maintenance workflow, from creating work requests and planning jobs to scheduling technicians and closing out work orders in a CMMS.
Reliability & Condition Monitoring: Scenarios focused on monitoring the health of critical equipment using techniques like vibration analysis or oil analysis to predict failures and plan proactive maintenance.
Asset Strategy & Planning: Scenarios related to developing long-term maintenance strategies for major assets, planning major shutdowns, and managing spare parts inventory.

## Use Case: Health, Safety & Environment (HSE)
Safety Management: Scenarios involving safety procedures like incident reporting, workplace inspections, issuing permits to work, and managing emergency response drills.
Environmental Compliance: Scenarios focused on monitoring and reporting environmental data, such as water quality, dust levels, and noise, to ensure compliance with regulations.
Water Management: Scenarios related to managing the mine's water balance, including dewatering operations, water treatment, and managing water storage facilities.

# Oil and Gas Core Functions
## Use Case: Upstream (Exploration & Production)
Geoscience & Exploration: Scenarios related to the analysis of seismic and geological data, identification of potential drilling targets, reservoir characterization, and prospect evaluation.
Drilling & Completions: Scenarios covering the planning, execution, and monitoring of drilling operations, well design, completions, and rig management.
Production Operations: Scenarios focused on monitoring and optimizing well performance, managing artificial lift systems, handling production chemicals, and real-time production surveillance.
Asset & Maintenance Management: Scenarios involving the scheduling of maintenance for surface and subsurface equipment (e.g., pumps, rigs), managing asset integrity, tracking equipment health, and planning work orders.

## Use Case: Midstream (Transportation & Storage)
Pipeline Operations & Control: Scenarios related to the real-time monitoring of pipeline flow, pressure, and temperature, leak detection, pigging operations, and managing compressor/pump stations.
Terminal & Storage Management: Scenarios focused on managing hydrocarbon inventory levels in storage tanks, scheduling receipts and deliveries, and overseeing blending operations.
Logistics & Scheduling: Scenarios covering the nomination and scheduling of pipeline capacity, coordinating truck, rail, or marine transport, and managing commodity movements.
Compliance & Safety: Scenarios involving adherence to transportation regulations, managing safety protocols, incident reporting, and right-of-way management.

## Use Case: Downstream (Refining & Marketing)
Refinery Operations & Optimization: Scenarios related to monitoring refinery unit performance, optimizing product yields and quality, managing energy consumption, and process control adjustments.
Supply & Trading: Scenarios focused on analyzing market data, executing trades for crude oil and refined products, managing price risk through hedging, and optimizing supply chain logistics.
Distribution & Retail: Scenarios covering the management of fuel inventory at retail stations, dispatching fuel delivery trucks, and handling B2B fuel sales and contracts.
Health, Safety & Environment (HSE): Scenarios involving the management of environmental compliance, tracking emissions, responding to safety incidents, managing permits to work, and ensuring personnel safety.

# Pharmaceuticals and Life Sciences Core Functions
## Use Case: Research & Development (R&D)
Drug Discovery & Target Identification: Scenarios related to analyzing genomic and proteomic data, identifying potential drug targets, and screening compound libraries for potential therapeutic candidates.

Preclinical Research: Scenarios focused on designing and managing preclinical studies (in vitro, in vivo), analyzing study data, and documenting experimental protocols and results in an Electronic Lab Notebook (ELN).

Lab & Sample Management: Scenarios involving the tracking of biological samples, managing reagent inventory, scheduling lab equipment usage, and ensuring compliance with lab safety protocols.

Research Data Analysis: Scenarios that cover the analysis of complex biological datasets, generating visualizations, collaborating on research findings, and preparing data for publication or internal review.

## Use Case: Clinical Trials
Trial Design & Feasibility: Scenarios related to protocol development, site selection, assessing patient population viability, and modeling trial costs and timelines.

Patient Recruitment & Enrollment: Scenarios focused on identifying eligible patients for clinical trials from EMR/EHR data, managing patient consent, and tracking enrollment progress against targets.

Clinical Data Management: Scenarios covering the design of electronic Case Report Forms (eCRFs), data entry, query resolution, and database lock procedures within an Electronic Data Capture (EDC) system.

Trial Operations & Monitoring: Scenarios involving the management of clinical trial supplies, monitoring site compliance with the protocol, tracking trial milestones, and managing payments to clinical sites.

## Use Case: Manufacturing & Supply Chain
Production & Batch Management: Scenarios related to production scheduling, managing manufacturing recipes, reviewing and approving electronic batch records (eBRs), and investigating production deviations.

Quality Control & Assurance: Scenarios focused on managing quality control testing, reviewing lab results against specifications, handling out-of-specification (OOS) investigations, and releasing product batches.

Inventory & Cold Chain Logistics: Scenarios involving the management of raw materials and finished product inventory, tracking temperature-sensitive shipments (cold chain), and ensuring product integrity during transport.

Supply Chain & Traceability: Scenarios covering drug serialization (e.g., DSCSA), tracking product from manufacturing to the dispenser, and managing recall operations.

## Use Case: Regulatory & Compliance
Submission Management: Scenarios related to compiling, publishing, and submitting regulatory dossiers (e.g., IND, NDA, MAA) to health authorities like the FDA or EMA.

Pharmacovigilance & Safety Reporting: Scenarios focused on processing adverse event reports from various sources, performing case assessments, and submitting expedited and periodic safety reports to regulatory agencies.

Quality Audits & Inspections: Scenarios involving the management of internal and external audits, responding to inspector findings, and tracking Corrective and Preventive Actions (CAPAs).

Regulatory Intelligence: Scenarios related to monitoring changes in global health regulations, assessing the impact on existing and pipeline products, and updating internal policies accordingly.

## Use Case: Commercial & Medical Affairs
Medical Information & Inquiries: Scenarios where medical information specialists respond to unsolicited inquiries from healthcare professionals about a product's efficacy, safety, or off-label use.

Key Opinion Leader (KOL) Engagement: Scenarios focused on identifying and managing relationships with influential experts in a therapeutic area, tracking engagements, and gathering insights.

Promotional Material Review: Scenarios covering the internal review and approval process for marketing and promotional materials to ensure they are medically accurate and compliant with regulations.

Patient Support Programs: Scenarios related to enrolling patients in support programs, providing educational resources, and managing patient assistance or co-pay programs.

# Ports Core Functions
## Use Case: Vessel Operations
Berth & Pilotage Management: Scenarios related to scheduling vessel arrivals and departures, assigning berths at the quay, and coordinating services with pilots and tugboats for safe navigation and docking.

Vessel Services & Husbandry: Scenarios covering the arrangement of essential ship services while in port. This includes bunkering (refueling), providing fresh water and provisions, managing waste disposal, and facilitating crew changes.

Mooring & Unmooring Operations: Scenarios focused on the physical tasks performed by linesmen to secure a vessel to the berth upon arrival and release it upon departure.

Vessel Traffic & Navigation: Scenarios involving the monitoring and management of all ship movements within the port's jurisdiction by the Vessel Traffic Service (VTS) to ensure safety and efficiency.

## Use Case: Terminal Operations
Yard & Stowage Planning: Scenarios related to the strategic planning of container placement within the terminal yard and the creation of detailed stowage plans for loading containers onto a vessel to ensure stability and efficient discharge at subsequent ports.

Quay & Crane Operations: Scenarios covering the management of loading and discharging cargo between the vessel and the quay. This involves the operation of ship-to-shore (STS) cranes and managing the sequence of container movements.

Horizontal Transport: Scenarios focused on the movement of containers and other cargo between the quayside, the container yard stacks, and the gate complex. This is typically done by terminal tractors, straddle carriers, or AGVs.

Special Cargo Handling: Scenarios involving the management of non-standard cargo, such as refrigerated containers (reefers), hazardous materials (HAZMAT), or oversized, out-of-gauge (OOG) items, which require special procedures.

## Use Case: Gate & Landside Operations
Gate Processing & Appointments: Scenarios covering the management of truck and hauler traffic entering and exiting the terminal. This includes processing documentation (e.g., Bill of Lading), inspecting containers, and managing vehicle appointments through a Vehicle Booking System (VBS).

Rail Operations: Scenarios focused on coordinating the arrival, positioning, loading, and unloading of trains at the port's intermodal rail facility.

Customs & Documentation: Scenarios related to handling customs declarations, managing container holds placed by regulatory bodies, and processing the necessary import/export paperwork to ensure legal compliance.

Warehouse & CFS Operations: Scenarios involving work at a Container Freight Station (CFS), such as stuffing (loading) and de-stuffing (unloading) cargo into and out of containers, and managing short-term cargo storage.

## Use Case: Port Administration & Finance
Billing & Invoicing: Scenarios focused on creating and sending invoices to customers (e.g., shipping lines, cargo owners) for port services such as stevedoring, wharfage, storage (demurrage), and other fees.

Asset Management & Maintenance: Scenarios related to the maintenance and repair of all port equipment, including cranes, terminal tractors, and straddle carriers. This involves scheduling preventive maintenance and responding to breakdowns.

Customer Service & Claims: Scenarios involving handling inquiries from shipping lines, freight forwarders, and trucking companies, resolving service issues, and processing claims for damaged or lost cargo.

Reporting & Analytics: Scenarios covering the generation of operational and financial reports, analyzing Key Performance Indicators (KPIs) like crane productivity or truck turnaround time, and forecasting future cargo volumes.

## Use Case: Health, Safety, Security & Environment (HSSE)
Safety & Incident Management: Scenarios related to managing workplace safety, conducting safety drills, issuing permits-to-work for hazardous tasks, and the formal reporting and investigation of any accidents or incidents.

Port Security & Access Control: Scenarios focused on maintaining port security in compliance with the ISPS (International Ship and Port Facility Security) Code. This includes managing access control for personnel and vehicles, monitoring surveillance systems, and patrolling facilities.

Environmental Compliance: Scenarios involving the monitoring and management of the port's environmental impact. This includes tracking air and water quality, managing ballast water and waste disposal, and responding to spills.

Emergency Response: Scenarios that cover the coordination of the port's response to major emergencies, such as fires, medical emergencies, security breaches, or severe weather events.

# Public Sector Core Functions
## Use Case: Citizen Services & Case Management
Benefits Administration: Scenarios related to applying for, managing, and renewing public assistance benefits such as unemployment, food assistance (SNAP), or housing aid. This includes eligibility determination, processing applications, and handling status inquiries.

Licensing & Permitting: Scenarios covering the lifecycle of licenses and permits issued by government agencies. This includes applications for driver's licenses, business permits, building permits, and professional licenses, as well as renewals and status checks.

Information & Inquiry Resolution: Scenarios focused on handling general citizen inquiries and service requests, often through a 311-style system. This includes providing information about public services, logging complaints, and routing requests to the correct department.

Case Management: Scenarios involving the ongoing management of individual or family cases by social service agencies. This includes intake, needs assessment, creating service plans, documenting interactions, and coordinating with multiple service providers.

## Use Case: Public Administration & Finance
Taxation & Revenue: Scenarios related to the collection of taxes and fees. This includes assisting citizens with filing income or property taxes, setting up payment plans for overdue taxes, and answering questions about tax assessments and bills.

Grants & Funding Management: Scenarios covering the management of government grants. This includes the application process for organizations seeking funding, reporting requirements for grant recipients, and oversight of fund distribution.

Procurement & Contracts: Scenarios focused on the government procurement process. This includes vendor registration, submitting bids for government contracts, managing contract awards, and processing vendor payments.

Budget & Financial Reporting: Scenarios related to the internal financial operations of a government agency, such as developing an annual budget, tracking departmental spending against appropriations, and generating public-facing financial reports.

## Use Case: Regulatory & Compliance
Inspections & Enforcement: Scenarios involving regulatory inspections and the enforcement of laws and codes. This includes scheduling and conducting health inspections for restaurants, building code inspections for construction projects, and issuing citations for violations.

Compliance Reporting: Scenarios where individuals or businesses are required to submit compliance reports to a government agency, such as environmental compliance reports or campaign finance disclosures.

Public Records & FOIA: Scenarios focused on managing and responding to public records requests under the Freedom of Information Act (FOIA) or similar state laws. This includes receiving requests, searching for documents, redacting sensitive information, and delivering the records.

Audit & Oversight: Scenarios covering the internal or external audit of government programs to ensure they are operating efficiently and in compliance with laws and regulations. This includes providing documentation to auditors and responding to audit findings.

## Use Case: Public Works & Infrastructure
Service Request Management: Scenarios related to citizens reporting issues with public infrastructure. This includes reporting potholes, broken streetlights, water main breaks, or missed trash collection, and tracking the status of the repair.

Asset Management: Scenarios focused on the management and maintenance of public assets, such as tracking the condition of roads, bridges, and public buildings, and scheduling preventive maintenance.

Project Management: Scenarios covering the management of public infrastructure projects, such as the construction of a new park or the renovation of a community center, including tracking timelines, budgets, and milestones.

Utility Billing: Scenarios related to billing for municipal utilities like water, sewer, and sanitation services. This includes setting up new service, processing payments, handling billing disputes, and answering questions about rates.

# Real Estate Core Functions
## Use Case: Residential & Commercial Sales
Lead & Client Management: Scenarios covering client intake, updating CRM entries, nurturing potential leads through follow-ups, and conducting initial needs assessments with buyers and sellers.

Property Listing & Marketing: Scenarios related to gathering property details, creating compelling listings for the MLS and other platforms, producing marketing materials (e.g., flyers, virtual tours), and coordinating open houses or showings.

Transaction Coordination: Scenarios focused on the administrative "contract-to-close" process. This includes managing transaction timelines, coordinating with lenders, title companies, and inspectors, and ensuring all documentation is complete and compliant.

Valuation & Market Analysis: Scenarios that involve researching comparable properties, preparing Comparative Market Analysis (CMA) reports for sellers, and analyzing local market trends to advise clients on pricing and offers.

## Use Case: Property Management
Leasing & Tenant Relations: Scenarios covering the full tenant lifecycle, from advertising vacancies and processing rental applications to lease signing, tenant onboarding, handling tenant inquiries and complaints, and managing lease renewals.

Maintenance & Vendor Management: Scenarios focused on receiving, logging, and dispatching maintenance requests. This includes coordinating with contractors and vendors, tracking the status of work orders, and scheduling preventive maintenance.

Financial Management & Reporting: Scenarios related to the financial oversight of properties. This includes rent collection, processing payments to vendors, managing property budgets, and generating financial statements (e.g., rent roll, profit & loss) for property owners.

Compliance & Legal: Scenarios involving adherence to housing laws and regulations. This includes conducting property inspections, managing lease violations, handling legal notices, and executing the eviction process when necessary.

Leasing & Marketing: Scenarios focused on advertising vacant units, scheduling and conducting showings, processing rental applications, and performing tenant screening (credit/background checks).

Tenant Relations: Scenarios covering the tenant lifecycle, including lease generation and signing, move-in/move-out inspections, handling tenant inquiries or complaints, and processing lease renewals or notices to vacate.

Maintenance & Operations: Scenarios related to managing maintenance requests, dispatching vendors, tracking work order status, and conducting routine property inspections.

Financial Management: Scenarios involving rent collection, processing owner distributions, paying property-related bills (e.g., HOA, taxes), and generating monthly financial statements for property owners.

Leasing & Tenant Screening: Scenarios covering the marketing of rental properties, processing applications, conducting background and credit checks, and executing lease agreements.

Rent Collection & Financials: Scenarios focused on processing monthly rent payments, managing security deposits, handling late fees, and preparing financial statements for property owners.

Maintenance & Repairs: Scenarios involving the handling of tenant maintenance requests, dispatching vendors, scheduling routine inspections, and managing property upkeep.

Tenant Relations & Renewals: Scenarios related to communication with tenants, resolving disputes, enforcing lease terms, and managing the lease renewal or move-out processes.

## Use Case: Residential Sales
Listing & Marketing: Scenarios related to creating property listings, coordinating professional photography, generating marketing copy, ordering photos, scheduling open houses, and launching and tracking marketing and advertising campaigns performance across various platforms (e.g., MLS, social media).

Buyer & Seller Management: Scenarios covering client onboarding, generating comparative market analysis (CMA) reports, managing client communications, and qualifying buyer leads.

Offer & Transaction Coordination: Scenarios focused on drafting and submitting purchase offers, managing counter-offers, coordinating inspections, and tracking contingency deadlines through to closing.

Closing & Post-Sale: Scenarios involving the coordination of the final closing process, reviewing settlement statements, and managing post-sale client follow-up.

Client Onboarding & Qualification: Scenarios related to initial consultations with buyers or sellers, understanding their needs and financial standing, and establishing an agency relationship.

Showings & Open Houses: Scenarios involving the scheduling, management, and follow-up for individual property showings, virtual tours, and public open house events.

Offers & Negotiation: Scenarios covering the submission, receipt, and negotiation of purchase offers and counter-offers between buyers and sellers.

Closing & Escrow: Scenarios related to managing the transaction from an accepted offer to the final closing. This includes coordinating with lenders, title companies, inspectors, and appraisers to ensure all contractual obligations are met.

## Use Case: Commercial Real Estate
Leasing & Tenant Representation: Scenarios related to finding suitable commercial spaces for clients, analyzing lease terms, negotiating letters of intent (LOI), and representing tenants in lease agreements.

Investment & Sales Analysis: Scenarios focused on analyzing commercial property investments, creating pro-forma financial models (e.g., cap rate, cash-on-cash return), conducting due diligence, and preparing investment memorandums.

Property & Asset Management: Scenarios covering the management of commercial properties, including tenant relations, lease administration, overseeing property operations, and strategic asset planning to maximize value.

Investment Sales: Scenarios covering the acquisition and disposition of income-generating commercial properties, including apartment complexes, office buildings, and retail centers.

Market Analysis & Valuation: Scenarios focused on performing detailed market research, analyzing comparable properties (comps), and creating property valuations using methods like cap rate analysis or discounted cash flow (DCF).

Due Diligence: Scenarios involving the comprehensive investigation of a commercial property prior to purchase. This includes reviewing financial records, physical inspections, environmental assessments, and verifying lease agreements.

## Use Case: Real Estate Development
Site Acquisition & Feasibility: Scenarios related to identifying and acquiring land or properties for development, conducting feasibility studies, analyzing zoning regulations, and assessing market potential.

Project Management & Entitlements: Scenarios focused on managing the development process, securing necessary permits and government approvals (entitlements), and overseeing construction progress, budgets, and timelines.

# Retail Core Functions
## Use Case: Store Operations
Point of Sale (POS) Transactions: Scenarios involving customer checkout, processing various payment types, applying discounts, and handling tax exemptions.

Store Opening & Closing: Scenarios covering daily operational checklists, cash management (e.g., float preparation, reconciliation), and system startups/shutdowns.

In-Store Customer Assistance: Scenarios where associates help customers locate products, provide product information, and check stock at other locations.

Task & Shift Management: Scenarios related to assigning tasks to associates, managing shift schedules, and monitoring task completion.

## Use Case: E-commerce & Order Management
Online Order Placement: Scenarios focused on the customer's journey of placing an order online, including adding items to a cart, applying promo codes, and completing checkout.

Order Fulfillment & Status: Scenarios covering the backend process of picking, packing, and shipping online orders, as well as providing customers with status updates and tracking information.

Click & Collect / BOPIS: Scenarios that manage the "Buy Online, Pick up In Store" process, including notifying customers when orders are ready and managing the in-store pickup experience.

Subscription Management: Scenarios related to managing recurring orders or subscription boxes, including sign-ups, modifications, and cancellations.

## Use Case: Customer Service & Support
Returns & Exchanges: Scenarios involving processing customer returns or exchanges for both in-store and online purchases, including inspecting items and issuing refunds or store credit.

Product Inquiries: Scenarios where customer service agents handle detailed questions about product specifications, warranty, or availability.

Issue Resolution: Scenarios focused on resolving customer complaints related to damaged products, shipping errors, or billing disputes.

Account Management: Scenarios related to helping customers manage their online accounts, including password resets and updating personal information.

## Use Case: Inventory & Merchandising
Stock Management: Scenarios covering inventory control processes like cycle counts, stock transfers between stores, and investigating inventory discrepancies.

Merchandising & Planograms: Scenarios related to executing in-store merchandising plans (planograms), setting up promotional displays, and ensuring product presentation standards are met.

Receiving & Restocking: Scenarios focused on receiving shipments from distribution centers, verifying contents against delivery manifests, and restocking shelves.

Pricing & Promotions: Scenarios involving the management of product pricing, including executing price changes, activating promotional offers, and ensuring price accuracy at the POS.

## Use Case: Marketing & Loyalty
Loyalty Program Management: Scenarios related to enrolling customers in the loyalty program, explaining benefits, and helping them redeem points or rewards.

Personalized Offers: Scenarios where the system generates and delivers personalized offers to customers based on their purchase history and browsing behavior.

Campaign Management: Scenarios covering the execution and tracking of marketing campaigns, such as email blasts or social media promotions.

Customer Feedback & Reviews: Scenarios focused on soliciting and managing customer feedback, including sending post-purchase surveys and responding to online product reviews.

# Smart Cities Core Functions
## Use Case: Urban Mobility & Transport
Traffic Management: Scenarios related to real-time traffic monitoring, adaptive traffic signal control, incident detection, and dynamic rerouting to alleviate congestion.
Public Transit Operations: Scenarios focused on managing public transportation fleets, including real-time vehicle tracking, schedule adherence, passenger counting, and dispatch optimization.
Parking Management: Scenarios covering the management of public parking spaces, including real-time availability tracking, dynamic pricing, and enforcement.
EV Charging & Micromobility: Scenarios related to managing electric vehicle charging stations and shared micromobility services (e.g., e-scooters, bikes), including station status, usage analytics, and maintenance.

## Use Case: Public Safety & Security
Emergency Response: Scenarios focused on optimizing emergency services dispatch (police, fire, medical) by using real-time data to locate incidents, assess severity, and coordinate units.
Public Space Monitoring: Scenarios involving the use of sensors and cameras to monitor public areas for safety hazards, crowd management, and detecting anomalies like gunshots or unusual activity.
Incident & Disaster Management: Scenarios covering the coordination of responses to large-scale incidents or natural disasters, including resource allocation, evacuation routing, and damage assessment.
Predictive Policing & Prevention: Scenarios that use historical data and real-time analytics to identify areas at high risk for certain types of crime, allowing for preventative patrols and resource deployment.

## Use Case: Utilities & Environment
Smart Grid & Energy Management: Scenarios related to monitoring and managing the electrical grid, including load balancing, outage detection and restoration (FLISR), and integrating renewable energy sources.
Water & Wastewater Management: Scenarios focused on the water supply system, including leak detection in pipes, monitoring water quality, managing reservoir levels, and optimizing wastewater treatment processes.
Waste Management: Scenarios covering the optimization of waste collection routes based on real-time fill levels of smart bins, reducing fuel consumption and unnecessary pickups.
Environmental Monitoring: Scenarios related to tracking environmental conditions, such as air quality, noise levels, and urban heat islands, to inform public health advisories and environmental policy.

## Use Case: Public Services & Governance
Citizen Reporting & Service Requests: Scenarios involving citizen-facing platforms (like a 311 system) for reporting non-emergency issues like potholes, broken streetlights, or graffiti, and tracking the resolution process.
Permit & License Management: Scenarios covering the application, review, and issuance of municipal permits and licenses (e.g., building permits, business licenses) through a digital platform.
Public Information & Alerting: Scenarios focused on disseminating information and alerts to the public regarding events, emergencies, road closures, or service disruptions via various channels.
Smart Asset Management: Scenarios related to tracking the condition and maintenance schedules of public infrastructure like bridges, roads, and public buildings using sensor data and predictive analytics.

## Use Case: Smart Buildings & Infrastructure
Building Automation & Control: Scenarios focused on managing city-owned buildings, including optimizing HVAC systems for energy efficiency, controlling access, and managing security systems.
Smart Street Lighting: Scenarios related to the remote control and monitoring of streetlights, including adjusting brightness based on real-time conditions, detecting faults, and tracking energy consumption.
Structural Health Monitoring: Scenarios involving the use of sensors to monitor the structural integrity of critical infrastructure like bridges and tunnels to detect stress, vibration, or defects.
Digital Twin & Urban Planning: Scenarios that utilize a virtual model (digital twin) of the city to simulate the impact of new developments, traffic patterns, or environmental changes to support urban planning decisions.

# Sports Core Functions
## Use Case: Team & Player Management
Player Scouting & Recruitment: Scenarios related to identifying, evaluating, and recruiting new talent. This includes analyzing performance data, watching game footage, and managing scouting reports.

Contract & Roster Management: Scenarios focused on negotiating player contracts, managing the team roster to comply with league rules (e.g., salary caps), and handling trades and player transfers.

Player Performance & Health: Scenarios involving the tracking and analysis of player performance metrics, managing player health and wellness, coordinating with medical staff, and planning training regimens.

Team Logistics & Travel: Scenarios covering the complex logistics of team operations, including scheduling travel, booking accommodations, arranging equipment transport, and managing team itineraries.

## Use Case: League & Competition Management
Scheduling & Fixtures: Scenarios related to creating and managing the season schedule, including setting game dates, times, and locations, and handling postponements or rescheduling.

Officiating & Rules Enforcement: Scenarios focused on managing referees and officials, interpreting and enforcing game rules, and utilizing technologies like video assistant referee (VAR).

Standings & Results Management: Scenarios involving the real-time recording of game results, updating league standings and leaderboards, and managing official statistics.

Disciplinary Actions: Scenarios covering the process of reviewing on-field incidents, investigating misconduct, and issuing fines, suspensions, or other penalties to players or teams.

## Use Case: Fan Engagement & Ticketing
Ticketing & Access Control: Scenarios related to the sale of tickets (season, single-game, group), managing ticket inventory, and operating access control systems at venues.

Membership & Loyalty Programs: Scenarios focused on managing fan membership and loyalty programs, including tracking points, delivering rewards, and offering exclusive benefits.

Fan Communications & Support: Scenarios involving communication with fans through various channels, handling inquiries and complaints, and managing fan club activities.

Merchandise & Concessions: Scenarios covering the management of team merchandise sales, both online and at the venue, as well as the operation of food and beverage concessions during events.

## Use Case: Broadcasting & Media
Media Rights & Distribution: Scenarios related to negotiating broadcast rights with television networks and streaming services, and managing the distribution of live game feeds to partners.

Live Broadcast Production: Scenarios focused on the technical production of a live game broadcast, including managing camera feeds, coordinating on-air talent, and inserting graphics and replays.

Digital Content & Streaming: Scenarios covering the creation and management of content for digital platforms, such as team websites, mobile apps, and social media, including live streaming games and creating highlight clips.

Sponsorship & Advertising: Scenarios involving the management of team and league sponsorships, including activating sponsorship deals and integrating advertising into broadcasts and venues.

## Use Case: Venue & Event Operations
Event Day Operations: Scenarios related to the overall management of a live sporting event, including coordinating staff, managing crowd flow, and ensuring a positive fan experience.

Venue Safety & Security: Scenarios focused on ensuring the safety and security of everyone at the venue, including managing security personnel, monitoring surveillance systems, and executing emergency response plans.

Facility & Turf Management: Scenarios covering the maintenance and preparation of the sports venue, including turf management for fields, court maintenance, and general facility upkeep.

Hospitality & VIP Services: Scenarios involving the management of premium seating, luxury suites, and other VIP hospitality services for high-value ticket holders and corporate partners.

# Tax Core Functions
## Use Case: Individual Tax Preparation & Filing
Data Collection & Input: Scenarios focused on gathering and entering taxpayer information. This includes processing standard tax forms (e.g., W-2, 1099s), importing financial data, and documenting sources of income and expenses.

Deductions & Credits Optimization: Scenarios related to identifying and calculating eligible tax deductions and credits to minimize tax liability. This includes itemized deductions (e.g., mortgage interest, state taxes), education credits, child tax credits, and retirement savings contributions.

Filing & E-Services: Scenarios covering the final stages of tax preparation. This includes preparing returns for electronic or paper filing, processing requests for filing extensions, and managing electronic signatures and submissions.

Payment & Refund Management: Scenarios focused on handling the financial outcome of a tax return. This includes setting up direct deposit for refunds, processing tax payments, and creating installment agreements for taxpayers who cannot pay their balance in full.

## Use Case: Business Tax Services
Corporate & Partnership Tax: Scenarios related to preparing and filing income tax returns for various business entities (C-Corps, S-Corps, Partnerships). This includes calculating net business income, handling depreciation of assets, and managing shareholder or partner basis.

Sales & Use Tax Compliance: Scenarios focused on the calculation, collection, and remittance of sales and use taxes. This includes determining taxability of goods/services in different jurisdictions, managing exemption certificates, and filing periodic sales tax returns.

Payroll & Employment Tax: Scenarios involving taxes related to employees. This includes calculating payroll tax withholdings, preparing quarterly and annual payroll tax reports (e.g., Form 941, 940), and handling employee benefits taxation.

Specialized & Excise Tax: Scenarios covering industry-specific or transaction-specific taxes. This includes fuel excise taxes, property taxes, and other specialized filings required for businesses in regulated industries.

## Use Case: Taxpayer Representation & Resolution
Notice & Correspondence Management: Scenarios focused on responding to notices and letters from tax authorities (e.g., IRS, state agencies). This includes interpreting notices, gathering supporting documentation, and drafting response letters.

Examination & Audit Support: Scenarios related to representing a client during a tax audit or examination. This includes preparing for the audit, communicating with the revenue agent, providing requested documentation, and negotiating adjustments.

Collections & Appeals: Scenarios involving post-assessment disputes and payment issues. This includes negotiating offers in compromise, setting up installment agreements, requesting penalty abatements, and filing appeals on audit decisions.

Account & Transcript Analysis: Scenarios focused on retrieving and analyzing official taxpayer records. This includes requesting and interpreting tax transcripts, checking account balances, and verifying payment and penalty history.

## Use Case: Tax Planning & Advisory
Individual & Family Planning: Scenarios related to providing strategic advice to individuals. This includes retirement planning, estimating tax liability for major life events (e.g., marriage, home purchase), and optimizing tax withholding.

Business Tax Strategy: Scenarios focused on advising businesses on tax-efficient strategies. This includes entity selection (e.g., S-Corp vs. LLC), planning for major transactions, and analyzing the tax implications of business decisions.

Estimated Tax & Projections: Scenarios involving the forecasting of tax liability. This includes calculating and processing quarterly estimated tax payments for self-employed individuals and businesses to avoid underpayment penalties.

Compliance & Risk Assessment: Scenarios related to proactively identifying potential tax issues. This includes reviewing past returns for audit risk, advising on documentation best practices, and ensuring compliance with new tax legislation.

# Telecom Core Functions
## Use Case: Customer Service
* **Billing and Payments:** Scenarios involving the explanation of charges, handling payment disputes, processing payments, and managing billing cycles.

* **Plan Management:** Scenarios focused on customer-initiated changes to their service plans, such as upgrades, downgrades, and adding or removing features (e.g., data packs, international calling).

* **Account Administration:** Scenarios related to the management of a customer's account details, including updating addresses, changing security settings, and adding or removing authorized users.

* **Service Lifecycle:** Scenarios that cover major service events like reporting outages, handling service cancellation requests, and retention efforts.

## Use Case: Technical Support
* **Mobile Device Troubleshooting:** Scenarios focused on diagnosing and resolving issues with mobile handsets, including signal problems, data connectivity, SIM card errors, and device-specific settings.

* **Broadband and Fixed-Line Support:** Scenarios involving home or business internet, landlines, or other fixed services. This includes connectivity issues, slow speeds, and hardware setup (modems/routers).

* **Value-Added Service Support:** Scenarios for services beyond basic connectivity, such as troubleshooting IPTV, streaming applications, voicemail, or other digital add-ons.

* **Advanced Diagnostics:** Scenarios that require the agent to guide a user through complex, multi-step diagnostic procedures or interpret detailed remote diagnostic data.

## Use Case: Sales & Onboarding
* **New Customer Acquisition:** Scenarios covering the full process of signing up a new customer, from initial plan recommendations and coverage checks to creating a new account.

* **Upselling and Cross-selling:** Scenarios where the agent attempts to increase the value of an existing account by offering hardware upgrades, additional service lines, or premium features.

* **Onboarding and Activation:** Scenarios focused on the initial experience of a new customer, including activating a new device or service and explaining the first bill.

* **Competitive Port-in:** Scenarios that specifically handle the process of a customer transferring their existing phone number from a competing carrier.

## Use Case: Network Operations
* **Fault Management:** Scenarios involving the detection, diagnosis, and resolution of failures in network hardware or software, such as a cell tower going offline.

* **Performance Management:** Scenarios focused on proactively monitoring and optimizing the network, including managing traffic congestion and ensuring quality of service.

* **Network Provisioning:** Scenarios related to the configuration and deployment of new network elements, such as activating a new cell site or router.

* **Security Operations:** Scenarios that involve responding to network security threats, such as DDoS attacks, identifying fraudulent activity, or investigating security alerts.

# Tourism Core Functions
## Use Case: Hospitality & Accommodations
Booking & Reservation Management: Scenarios focused on the entire lifecycle of a reservation. This includes searching for availability, creating new bookings, modifying existing reservations (e.g., changing dates, room types), and processing cancellations.

Guest Services & In-Stay Support: Scenarios related to guest interactions during their stay. This covers handling check-in/check-out, processing service requests (e.g., room service, maintenance, housekeeping), and answering inquiries about property amenities.

Billing & Folio Management: Scenarios involving all financial aspects of a guest's stay. This includes managing the guest's bill (folio), posting charges for services, processing payments, handling billing disputes, and splitting folios.

Loyalty & Guest Relations: Scenarios focused on managing guest profiles and loyalty programs. This includes enrolling guests in loyalty programs, applying points or rewards, managing guest preferences, and handling post-stay feedback.

## Use Case: Transportation & Travel
Itinerary Planning & Booking: Scenarios related to booking flights, cruises, car rentals, or train tickets. This includes searching for options, creating multi-segment itineraries, selecting seats, and completing the booking process.

Disruption Management: Scenarios focused on handling unexpected changes to travel plans. This includes processing flight cancellations or delays, rebooking passengers, managing accommodation for stranded travelers, and handling lost luggage claims.

Ticketing & Documentation: Scenarios involving the issuance and management of travel documents. This covers issuing e-tickets, boarding passes, and travel vouchers, as well as handling requests for travel confirmations and receipts.

Ancillary Services & Upgrades: Scenarios related to selling additional products and services. This includes adding checked baggage, offering seat upgrades, selling travel insurance, and booking in-flight meals or onboard activities.

## Use Case: Tours & Attractions
Activity Booking & Scheduling: Scenarios focused on reserving spots for tours, attractions, or activities. This includes checking availability for specific time slots, booking tickets for museums or theme parks, and managing capacity for guided tours.

Visitor Information & Support: Scenarios related to providing information to visitors. This includes answering questions about operating hours, locations, accessibility, and event schedules, as well as providing directions or recommendations.

Package & Itinerary Creation: Scenarios involving the bundling of multiple products into a single package. This includes creating vacation packages (e.g., flight + hotel + tour), custom itineraries, and applying package discounts.

Access & Entry Management: Scenarios related to managing visitor entry. This covers validating tickets or vouchers at an entrance, issuing timed-entry passes, and managing access control for special events or restricted areas.

# Transportation Core Functions
## Use Case: Trucking & Freight Operations
Dispatch & Load Management: Scenarios focused on assigning drivers to loads, optimizing routes, managing pickup and delivery schedules, and tracking driver Hours of Service (HOS) to ensure compliance.

Fleet Maintenance: Scenarios related to managing the health and readiness of the vehicle fleet. This includes scheduling preventive maintenance, responding to vehicle breakdowns, managing repair orders, and tracking parts inventory.

Safety & Compliance: Scenarios covering adherence to safety protocols and government regulations. This includes logging safety incidents, managing driver qualification files, conducting compliance audits, and handling roadside inspection reports.

Billing & Settlements: Scenarios involving the financial aspects of freight movement. This includes creating freight invoices, processing driver pay and settlements, managing fuel receipts and IFTA reporting, and handling accessorial charges like detention.

## Use Case: Public Transit Operations
Service Planning & Scheduling: Scenarios related to designing and managing transit routes and schedules. This includes creating new routes, adjusting timetables based on demand, planning for detours around construction or events, and managing run cutting.

Real-time Operations & Control: Scenarios focused on the daily management of the transit network. This includes monitoring real-time vehicle locations (AVL), managing service headways, responding to service disruptions (e.g., accidents, vehicle breakdowns), and dispatching support staff.

Passenger Information Systems: Scenarios covering the communication of service information to the public. This includes updating real-time arrival predictions, managing service alert notifications (e.g., delays, detours), and providing trip-planning assistance.

Fare & Revenue Management: Scenarios involving the fare collection and revenue side of operations. This includes managing smart card systems (e.g., adding value, reporting lost cards), processing mobile and contactless payments, and analyzing ridership and revenue data.

## Use Case: Ride-Sharing & On-Demand Mobility
Driver & Vehicle Onboarding: Scenarios covering the process of bringing new drivers onto the platform. This includes managing applications, processing background checks, verifying vehicle inspections and documentation, and activating new driver accounts.

Matching & Dispatch: Scenarios related to the core function of connecting riders with drivers. This includes the algorithmic matching process, managing dynamic (surge) pricing, optimizing multi-stop trip routes, and handling pre-scheduled ride requests.

Customer & Driver Support: Scenarios focused on resolving issues that occur before, during, or after a trip. This includes handling payment disputes, finding lost items, addressing complaints about driver or rider behavior, and managing account access issues.

Safety & Incident Response: Scenarios covering the management of safety-related events. This includes responding to accident reports, managing trust and safety investigations, temporarily or permanently deactivating accounts for policy violations, and liaising with law enforcement.

## Use Case: Rail Operations
Train & Crew Management: Scenarios related to the assembly of trains and assignment of crews. This includes building train consists (linking locomotives and railcars), managing crew rosters, ensuring crew members are qualified for their routes, and tracking rest periods.

Network Control & Dispatch: Scenarios focused on the safe movement of trains across the rail network. This includes controlling signals and track switches (interlockings), issuing track authorities or warrants to trains, and managing rail traffic to prevent conflicts.

Yard & Terminal Management: Scenarios covering activities within a rail yard. This includes managing the switching of railcars to build or break down trains, planning car movements (creating switch lists), and tracking inventory within the yard.

Intermodal Operations: Scenarios focused on the transfer of freight between different modes of transport, typically at a terminal. This includes coordinating the lifting of containers between trains and trucks, managing terminal gate operations, and tracking container availability (e.g., chassis management).

# Utilities Core Functions
## Use Case: Customer Service (Electric, Water, Gas)
Billing & Account Management: Scenarios related to starting, stopping, or transferring service, handling billing inquiries and disputes, setting up payment arrangements, and updating customer account information.

Outage Management: Scenarios focused on customers reporting service outages (power, water), receiving Estimated Times of Restoration (ETRs), and getting updates on repair status.

Service Orders: Scenarios covering field service requests, such as investigating low water pressure, trimming trees near power lines, responding to gas odor calls, or scheduling meter checks and repairs.

Conservation & Efficiency: Scenarios involving customer engagement with utility programs, such as applying for energy efficiency rebates, enrolling in Time-of-Use (TOU) rates, or inquiring about conservation tips.

## Use Case: Grid Operations (Electric)
System Control & Monitoring: Scenarios related to the real-time operation of the electric grid, including balancing load and generation, managing voltage and frequency, and performing economic dispatch of power plants.

Fault Location, Isolation, and Service Restoration (FLISR): Scenarios focused on the automated detection of faults on the distribution network, isolating the faulted section, and rerouting power to restore service to unaffected customers.

Distribution Automation: Scenarios involving the operation of smart grid devices like automated switches, capacitors, and reclosers to optimize grid performance, manage power quality, and support distributed energy resources (DERs).

Asset Management: Scenarios covering the lifecycle management of grid assets, including monitoring the health of transformers, poles, and lines, analyzing inspection data (from drones, LiDAR), and planning for replacement or refurbishment.

## Use Case: Water & Wastewater Operations
Treatment & Quality: Scenarios related to managing water and wastewater treatment plants, monitoring water quality in real-time, adjusting chemical dosages, and ensuring compliance with environmental regulations.

Network Management: Scenarios focused on the operation of the water distribution and wastewater collection systems, including managing pump stations, controlling pressure, monitoring storage tank levels, and detecting leaks.

Asset Management: Scenarios involving the maintenance and inspection of water and sewer infrastructure, such as dam safety inspections, pipeline condition assessments, and planning for water main replacements or flushing programs.

## Use Case: Gas Operations
Pipeline & Pressure Management: Scenarios related to the safe and reliable operation of the natural gas pipeline system, including monitoring and controlling pressure, managing compressor stations, and scheduling gas nominations.

Leak Detection & Repair: Scenarios covering the response to suspected gas leaks, including emergency dispatch, public safety communication (e.g., 'Call Before You Dig'), and investigating excavation damages.

Asset Management: Scenarios focused on maintaining the integrity of the gas system, such as performing internal pipeline inspections with PIGs, monitoring for corrosion, testing safety valves, and managing meter replacement programs.

# Venues Core Functions
## Use Case: Event Management & Booking
Event Booking & Contracting: Scenarios related to handling initial booking inquiries, checking date availability, negotiating contracts, and confirming event reservations.

Event Planning & Coordination: Scenarios focused on the detailed planning phase of an event. This includes coordinating with clients on logistics, layout, technical needs, and scheduling.

Vendor & Partner Management: Scenarios involving the coordination with third-party vendors, such as caterers, security firms, or equipment rental companies, ensuring they meet venue standards and event requirements.

Settlement & Post-Event Reporting: Scenarios covering the final financial settlement with the client, processing final payments, and generating post-event reports on attendance, sales, and operational metrics.

## Use Case: Ticketing & Box Office
Ticket Sales & Transactions: Scenarios related to the sale of tickets through various channels (online, box office, phone), including processing payments, handling group sales, and managing ticket allocations.

Access Control & Entry Management: Scenarios focused on the day-of-event operations for getting patrons into the venue. This includes scanning tickets, troubleshooting entry issues, and managing gate flow.

Box Office Operations: Scenarios involving the management of the physical box office, such as will-call services, resolving ticket disputes, and handling last-minute sales or seat changes.

Ticket Administration: Scenarios covering the backend management of ticketing, such as processing refunds, handling fraudulent ticket claims, and managing season ticket holder accounts.

## Use Case: Guest & Patron Services
General Inquiries & Support: Scenarios focused on handling general questions from guests about the venue, event details, policies (e.g., bag policy), and amenities.

Accessibility & Special Needs: Scenarios related to assisting guests with disabilities. This includes managing accessible seating, coordinating wheelchair assistance, and providing information on accessible services.

Issue Resolution & Complaints: Scenarios involving the real-time resolution of guest complaints during an event, such as seating issues, facility problems, or conflicts with other patrons.

Lost & Found: Scenarios covering the process of logging lost items, searching for found items, and coordinating the return of property to guests.

## Use Case: Venue Operations & Logistics
Staffing & Scheduling: Scenarios related to scheduling event staff (e.g., ushers, ticket takers, security), managing check-ins, and reallocating staff in real-time based on event needs.

Security & Emergency Response: Scenarios focused on managing venue security, dispatching guards to incidents, monitoring CCTV, and executing emergency response protocols (e.g., medical emergencies, evacuations).

Housekeeping & Maintenance: Scenarios involving the management of cleaning crews, responding to immediate cleanup needs (e.g., spills), and logging facility maintenance requests.

Event Setup & Changeover: Scenarios covering the logistical setup and teardown for events. This includes converting the venue from one configuration to another (e.g., from a concert setup to a basketball court).

## Use Case: Food & Beverage (Concessions)
Point of Sale (POS) & Ordering: Scenarios related to the operation of concession stands, including processing orders, handling payments, and managing digital or mobile ordering systems.

Inventory Management: Scenarios focused on tracking food and beverage inventory levels, placing orders with suppliers, and managing stock to prevent shortages during events.

Staff & Stand Management: Scenarios involving the assignment of staff to concession stands, monitoring performance, and resolving operational issues like equipment failure.

## Use Case: Sales & Hospitality
Premium Seating & Suite Sales: Scenarios related to selling and servicing premium seating, such as luxury suites and club seats. This includes managing contracts, processing payments, and coordinating amenities.

Group Sales: Scenarios focused on managing ticket sales for large groups, including schools, corporations, or tour operators, often involving special pricing and reserved blocks of seats.

VIP & Hospitality Management: Scenarios covering the coordination of services for VIP guests, such as managing guest lists, arranging special access, and fulfilling hospitality riders for artists or athletes.

# Wholesale Core Functions
## Use Case: Order Management & Sales
Quoting & Order Placement: Scenarios related to providing price quotes to retailers, handling bulk order inquiries, and receiving and entering new purchase orders into the system.

Order Processing & Fulfillment: Scenarios covering the internal process of allocating stock, confirming order details, and coordinating with the warehouse to prepare orders for shipment.

Invoicing & Payments: Scenarios focused on generating invoices for customers, managing credit terms, processing payments, and handling collections for overdue accounts.

Customer Account Management: Scenarios involving the management of retailer accounts, including setting up new accounts, managing credit limits, and updating contact and shipping information.

## Use Case: Inventory & Warehouse Management
Receiving & Putaway: Scenarios related to receiving inbound shipments from suppliers, verifying contents against purchase orders, and storing goods in the correct warehouse locations.

Inventory Control: Scenarios focused on maintaining accurate inventory records, performing cycle counts, managing stock levels, and investigating discrepancies.

Picking, Packing, & Shipping: Scenarios covering the process of picking items from warehouse locations to fulfill orders, packing them for shipment, generating shipping labels and manifests, and loading them onto trucks.

Returns Management (RMA): Scenarios involving the processing of return merchandise authorizations (RMAs) from customers, inspecting returned goods, and issuing credits or replacements.

## Use Case: Supplier & Procurement Management
Purchase Order Management: Scenarios related to creating and sending purchase orders to suppliers, tracking order status, and managing delivery schedules.

Supplier Relationship Management: Scenarios focused on communicating with suppliers, negotiating pricing and terms, evaluating supplier performance, and resolving supply chain issues.

Inbound Logistics: Scenarios covering the management of incoming shipments from suppliers, including scheduling deliveries, coordinating with freight carriers, and managing customs clearance for international shipments.

Quality Assurance & Compliance: Scenarios involving the inspection of incoming goods to ensure they meet quality standards and comply with regulatory requirements.

## Use Case: Customer & Retailer Support
Product & Catalog Inquiries: Scenarios where wholesale customer service agents handle inquiries from retailers about product specifications, availability, and pricing from the product catalog.

Shipment & Delivery Support: Scenarios focused on providing retailers with tracking information for their orders, handling inquiries about shipping delays, and resolving delivery issues.

Claims & Dispute Resolution: Scenarios covering the process of managing customer claims for damaged goods, short shipments, or pricing discrepancies, and resolving disputes.

Retailer Onboarding & Training: Scenarios related to setting up new retailers in the system, providing them with access to ordering portals, and training them on products and processes.