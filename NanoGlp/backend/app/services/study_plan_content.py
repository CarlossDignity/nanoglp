"""
FAZ 8.2 — Study Plan (.docx) şablona özgü GLP metin kütüphanesi.

`nanolab_ic_study_plan_template.docx` ana şablonu ISO 10993-23 (İntrakütanöz Reaktivite) metni taşır.
ISO_10993_23_IC dışındaki şablonlar için Bölüm 1 (Objective), 5 (Materials & Methods), 6 (Test System),
7 (Animal Welfare), 8 (HADYEK), 9 (Experimental Design), 10 (Observations), 11 (Pathology), istatistik,
veri derleme ve rapor satırları bu kütüphanedeki İngilizce GLP metinleriyle değiştirilir.

Metin içi yer tutucular: {TEST_ITEM} {POLAR} {NONPOLAR} {RATIO} {TEMP} {HOURS} {N_ANIMALS} {CAGES} {STANDARD}
Metinler Study Director tarafından gözden geçirilmelidir (belgede açıkça belirtilir).
"""
from typing import Any, Dict

# Orijinal (ISO 10993-23 şablonu) H2 başlıkları — kütüphane bu başlıklara göre anahtarlanır
H_EXTRACT = "Preparation of Test Item Extract"
H_SITE = "Preparation of Test Site"
H_ROUTE = "Route of Administration and Justification for Selection"
H_DOSE = "Dose Selection, Concentration and Justification for Selection"
H_ADMIN = "Administration of Test Item"
H_OBS = "Intracutaneous Reactions"
H_CLIN = "Clinical signs of toxicity and Mortality"
H_BW = "Body weight"
H_EUTH = "Euthanasia"
H_VEHICLE = "Selection of Vehicle and Justification"
H_POSCTRL = "Positive Control Response Validation"
H_JUSTIF = "Justification for the selection of test system and reason for the route or method of administration"

_RABBIT_HOUSING: Dict[str, str] = {}

_EXTRACT_ANIMAL = (
    "Preparation of the test item extract for the {TITLE} of {TEST_ITEM} according to {STANDARD} will be conducted at the "
    "sponsor's request, in accordance with ISO 10993-12 Biological Evaluation of Medical Devices — Part 12 “Sample Preparation "
    "and Reference Materials”. The extraction process will be carried out using {POLAR} and {NONPOLAR} solvents at a ratio of "
    "{RATIO}, at {TEMP} °C for {HOURS} hours in a shaking water bath. The condition of the test extract (e.g., color, clarity, "
    "and presence of any particulates) will also be described in the report. All materials and equipment required for the test "
    "meet the requirements of the relevant standards, and their suitability will be verified prior to the study."
)

TEMPLATE_CONTENT: Dict[str, Dict[str, Any]] = {
    # ------------------------------------------------------------------ ISO 10993-6
    "ISO_10993_6_IMP": {
        "part_phrase": "Part 6 Tests for Local Effects after Implantation",
        "reference": (
            "International Standard ISO 10993-6:2016 Biological Evaluation of Medical Devices — Part 6 Tests for Local "
            "Effects after Implantation"
        ),
        "objective": (
            "The objective of this study is to evaluate the local biological (tissue) response to the test item, "
            "{TEST_ITEM}, following subcutaneous implantation in New Zealand White rabbits for the implantation period "
            "defined in the study schedule, by macroscopic and histopathological assessment of the implant sites in "
            "accordance with ISO 10993-6."
        ),
        "sections": {
            H_VEHICLE: (
                None,
                "No vehicle is required for this study. The test item will be implanted directly in its final (sterile) form as "
                "supplied by the sponsor; where the test item is a gel, paste or injectable, it will be administered as supplied "
                "without dilution. The negative control (reference) material will be implanted at contralateral sites under "
                "identical conditions. Details will be provided in the raw data and final report.",
            ),
            H_POSCTRL: (
                None,
                "A concurrent positive control has not been included in this study. The suitability of the rabbit subcutaneous "
                "implantation model is verified by the use of a negative control (reference) material and the historical data of "
                "the test facility. The negative control results will be incorporated in the study report.",
            ),
            H_JUSTIF: (
                None,
                "Rabbits were chosen as the test system because this species is widely accepted for implantation studies of "
                "medical devices and has sufficient dorsal subcutaneous tissue to accommodate multiple implant sites. The route "
                "is subcutaneous implantation, which represents the intended tissue contact of the test item and meets the "
                "local-effects requirements of ISO 10993-6 Biological Evaluation of Medical Devices — Part 6 Tests for Local "
                "Effects after Implantation.",
            ),
            H_EXTRACT: (
                "Preparation of Test Item and Implants",
                "The test item will be prepared for implantation in accordance with ISO 10993-6 and ISO 10993-12 “Sample "
                "Preparation and Reference Materials”. The test item will be implanted in its final sterile form; the condition, "
                "size, shape and sterility of the test item and of the negative control material will be documented in the raw "
                "data and the final report. All instruments and materials required for the procedure will be sterile and their "
                "suitability will be verified prior to the study.",
            ),
            H_SITE: (
                "Preparation of Implantation Site",
                "Approximately 4 to 18 hours before implantation, fur on the dorsal region of the animals will be removed by "
                "clipping closely using an electric hair clipper. Immediately before the procedure the skin will be disinfected. "
                "Surgical procedures will be performed under appropriate anaesthesia and analgesia as per current veterinary "
                "practice and Nanolab SOPs. Animals with healthy intact skin will be used.",
            ),
            H_ROUTE: (
                "Route of Implantation and Justification for Selection",
                "The test item and the negative control material will be implanted subcutaneously at separate sites on the "
                "dorso-lateral paravertebral region of each rabbit (test item on one side of the spine and control material on "
                "the contralateral side) as per ISO 10993-6. The subcutaneous route is justified because it allows evaluation "
                "of the local tissue response to the test item at a site representing clinical tissue contact.",
            ),
            H_DOSE: (
                "Implant Selection, Size and Justification for Selection",
                "The amount/size of the test item and the number of implant sites will be selected in accordance with ISO "
                "10993-6 so that the implant is representative of the finished device and does not cause mechanical irritation "
                "unrelated to the material. The same size/volume of the negative control material will be implanted. Details "
                "will be recorded in the raw data and the final report.",
            ),
            H_ADMIN: (
                "Implantation Procedure",
                "On the day of implantation, the test item will be implanted subcutaneously at the designated sites on one side "
                "of the dorsal midline and the negative control material at the corresponding sites on the contralateral side of "
                "each rabbit. The incision(s) will be closed as per Nanolab SOP and the implant site locations will be "
                "documented for each animal.",
            ),
            H_OBS: (
                "Local Tissue Reactions at Implant Sites",
                "The implant sites will be examined for signs of local reaction (erythema, oedema, swelling, haematoma, "
                "infection, wound dehiscence) immediately after implantation, at 24, 48 and 72 hours (±2 hours) and "
                "subsequently at weekly intervals until the end of the implantation period (28 days). The observations will be "
                "recorded in the raw data and reported in the study report.",
            ),
            H_BW: (
                None,
                "The individual animal body weight will be recorded at receipt, prior to implantation (Day 0 of treatment), "
                "weekly during the implantation period and at termination.",
            ),
            H_EUTH: (
                "Euthanasia, Necropsy and Histopathology",
                "At the end of the implantation period, animals will be euthanized as per standard procedures. A detailed "
                "macroscopic examination of the implant sites and surrounding tissue will be performed; the implant sites (test "
                "item and control) with surrounding tissue will be excised, fixed in 10% neutral buffered formalin and processed "
                "for histopathological evaluation of the tissue response. If any animal gets injured, ill or moribund during the "
                "study, care will be taken as per current veterinary practices and the sponsor will be informed.",
            ),
        },
        "grading": {
            "title": "Macroscopic and Histopathological Scoring of Tissue Reaction (ISO 10993-6)",
            "headers": ["Parameter", "Semi-quantitative Score"],
            "rows": [
                ["Inflammatory cells (polymorphonuclear cells, lymphocytes, plasma cells, macrophages, giant cells)",
                 "0 = absent; 1 = rare; 2 = mild; 3 = moderate; 4 = marked / packed"],
                ["Necrosis", "0 = absent; 1 = minimal; 2 = mild; 3 = moderate; 4 = marked"],
                ["Neovascularisation", "0 = absent; 1 = minimal; 2 = mild; 3 = moderate; 4 = marked"],
                ["Fibrosis / capsule formation", "0 = absent; 1 = minimal; 2 = mild; 3 = moderate; 4 = marked"],
                ["Fatty infiltrate", "0 = absent; 1 = minimal; 2 = mild; 3 = moderate; 4 = marked"],
            ],
            "footnote": (
                "The score of the test item sites will be compared with that of the negative control sites. Other adverse "
                "changes at the implant sites shall be recorded and reported."
            ),
        },
        "statistics": (
            "Tissue reactions at the implant sites will be scored macroscopically and histopathologically for each observation "
            "period. For each animal, the scores of the test item sites will be compared with those of the negative control "
            "sites and the mean difference will be calculated. The test item will be considered to meet the requirements of the "
            "study if the local tissue response is not significantly greater than that of the negative control material. "
            "Statistical methods are not applicable unless otherwise specified; interpretation will be performed as per ISO "
            "10993-6."
        ),
        "data_compilation": (
            "Data will be summarized in tabular form showing, for each animal and observation period, the macroscopic "
            "observations at the implant sites, the histopathological scores of the test item and control sites, body weights, "
            "signs of toxicity, and the number of animals found dead or sacrificed for humane reasons (if any)."
        ),
        "test_system": {
            "Number of animals": "{N_ANIMALS} animals (each animal receives test item and control implants at separate subcutaneous sites)",
        },
        "housing": _RABBIT_HOUSING,
        "report_lines": {
            "Vehicle: justification of choice of vehicle.": "Test item form and justification of the implantation approach.",
            "Technique of injection site preparation;": "Technique of implantation site preparation;",
            "Details of injection technique;": "Details of implantation technique and implant site arrangement;",
            "Details of test substance preparation, application;": "Details of test item and negative control preparation, size and implantation;",
            "Positive Control Response Validation:": "Negative control (reference) material:",
            "A summary of the results of the latest Positive Control Response Validation including information on substance, concentration and vehicle used.":
                "Identification of the negative control (reference) material and implant site arrangement.",
            "Grading system;": "Scoring system (macroscopic and histopathological);",
            "Grading of Intracutaneous reaction.": "Macroscopic and histopathological evaluation of tissue reaction at the implant sites.",
        },
    },
    # ------------------------------------------------------------------ ISO 10993-5
    "ISO_10993_5_CYTO": {
        "part_phrase": "Part 5 Tests for In Vitro Cytotoxicity",
        "reference": (
            "International Standard ISO 10993-5:2009 Biological Evaluation of Medical Devices — Part 5 Tests for In Vitro "
            "Cytotoxicity"
        ),
        "objective": (
            "The objective of this study is to evaluate the potential cytotoxic effect of extracts of the test item, "
            "{TEST_ITEM}, on L929 mammalian (mouse) fibroblast cell cultures in vitro by qualitative (morphological) and "
            "quantitative (MTT cell viability) assessment in accordance with ISO 10993-5."
        ),
        "sections": {
            H_VEHICLE: (
                "Selection of Extraction Vehicle (Culture Medium) and Justification",
                "Extraction will be performed in complete cell culture medium (e.g., MEM supplemented with serum) as the "
                "extraction vehicle, in accordance with ISO 10993-12 “Sample Preparation and Reference Materials”. Vehicle "
                "details and justification will be provided in the raw data and final report. Extraction vehicle (blank) "
                "controls will be run in parallel.",
            ),
            H_POSCTRL: (
                "Positive and Negative Control Validation",
                "A concurrent positive control (a material known to be cytotoxic) and a negative control (e.g., high-density "
                "polyethylene) will be included in this study to verify the sensitivity and suitability of the test system. The "
                "control results will be incorporated in the study report.",
            ),
            H_JUSTIF: (
                "Justification for the selection of the in vitro test system",
                "The L929 mouse fibroblast cell line was chosen as the test system because it is a well-characterized mammalian "
                "cell line recommended by ISO 10993-5 for the cytotoxicity testing of medical device extracts. Cell viability is "
                "evaluated by the MTT assay and cell morphology, which meets the requirements of ISO 10993-5 Biological "
                "Evaluation of Medical Devices — Part 5 Tests for In Vitro Cytotoxicity. No live animals are used in this study.",
            ),
            H_EXTRACT: (
                None,
                "Preparation of the test item extract for the In Vitro Cytotoxicity Test of {TEST_ITEM} according to ISO 10993-5 "
                "will be conducted in accordance with ISO 10993-12. The extraction will be carried out using complete cell "
                "culture medium at a ratio of {RATIO}, at 37 ± 1 °C for 24 ± 2 hours in a CO2 incubator / oven (EQ-INC-001 / "
                "EQ-OVN-001). The condition of the extract (colour, clarity, presence of particulates and pH change) will be "
                "described in the report. All materials and equipment required for the test meet the requirements of the "
                "relevant standards, and their suitability will be verified prior to the study.",
            ),
            H_SITE: (
                "Cell Culture and Seeding",
                "L929 cells will be maintained in complete culture medium in a CO2 incubator (37 °C, 5% CO2, humidified "
                "atmosphere). Cells in the exponential growth phase will be seeded into 96-well culture plates at the defined "
                "density and incubated until a sub-confluent monolayer is obtained. Cell passage number, viability and seeding "
                "density will be recorded in the raw data.",
            ),
            H_ROUTE: (
                "Exposure Method and Justification for Selection",
                "The culture medium of the sub-confluent cells will be replaced with the test item extract, the blank (vehicle) "
                "control, the negative control extract and the positive control extract, and the cells will be incubated in the "
                "CO2 incubator for 24 ± 2 hours (37 °C, 5% CO2). The extract (indirect contact) method is selected as per ISO "
                "10993-5 since it enables evaluation of leachable substances released from the test item.",
            ),
            H_DOSE: (
                "Extract Concentration and Justification for Selection",
                "The undiluted (100%) test item extract and, where applicable, a serial dilution series of the extract will be "
                "tested. The use of the undiluted extract and its dilutions is consistent with ISO 10993-5 and ISO 10993-12 and "
                "enables a dose–response evaluation of the potential cytotoxicity.",
            ),
            H_ADMIN: (
                "Assessment of Cytotoxicity",
                "After the exposure period, the cell cultures will be examined microscopically for morphological changes and "
                "cell viability will be determined quantitatively by the MTT assay (formazan absorbance measured with a "
                "spectrophotometer / microplate reader). Viability is expressed as a percentage of the blank (vehicle) control. "
                "A reduction of cell viability by more than 30% (viability below 70%) is considered a cytotoxic effect as per "
                "ISO 10993-5.",
            ),
            H_OBS: (
                "Qualitative (Morphological) Evaluation of Cytotoxicity",
                "After the 24 ± 2 hour exposure, the cell cultures will be examined under an inverted microscope and the "
                "morphological changes (cell rounding, detachment, lysis, intracytoplasmic granules) will be graded using the "
                "reactivity grades given below for each culture. The observations will be recorded in the raw data and reported "
                "in the study report.",
            ),
            H_CLIN: (
                "Quantitative Evaluation of Cell Viability (MTT Assay)",
                "After microscopic evaluation, MTT solution will be added to each well and the plates will be incubated in the "
                "CO2 incubator; the formazan formed will be dissolved and its absorbance measured at the appropriate wavelength. "
                "Cell viability (%) will be calculated relative to the blank (vehicle) control. Results below 70% of the blank "
                "control indicate a cytotoxic potential.",
            ),
            H_BW: (
                "Culture Conditions Monitoring",
                "Incubator conditions (temperature, CO2 concentration and humidity), cell passage number, seeding density and the "
                "appearance of the blank and control cultures will be monitored and recorded in the raw data throughout the study.",
            ),
            H_EUTH: (
                "Disposal of Biological Material",
                "Not applicable (no animals are used). At the end of the study, all cell cultures, extracts and biohazard waste "
                "will be decontaminated and disposed of as per Nanolab SOPs.",
            ),
        },
        "grading": {
            "title": "Reactivity Grades for Qualitative Morphological Evaluation of Cytotoxicity (ISO 10993-5)",
            "headers": ["Grade / Reactivity", "Condition of Cultures"],
            "rows": [
                ["0 — None", "Discrete intracytoplasmic granules; no cell lysis"],
                ["1 — Slight", "Not more than 20% of the cells are round, loosely attached and without intracytoplasmic granules; occasional lysed cells"],
                ["2 — Mild", "Not more than 50% of the cells are round and devoid of intracytoplasmic granules; no extensive cell lysis and empty areas between cells"],
                ["3 — Moderate", "Not more than 70% of the cell layers contain rounded cells and/or are lysed"],
                ["4 — Severe", "Nearly complete destruction of the cell layers"],
            ],
            "footnote": (
                "Reactivity of Grade 3 and 4 is considered a cytotoxic effect. Other adverse changes in the cell cultures shall "
                "be recorded and reported."
            ),
        },
        "statistics": (
            "The mean absorbance values of the replicate wells will be calculated for each extract, blank control, negative "
            "control and positive control, and cell viability (%) will be expressed relative to the blank control. The test "
            "item will be considered non-cytotoxic if the cell viability is 70% or more of the blank control and the "
            "morphological reactivity is not greater than Grade 2, provided that the validity criteria of the negative and "
            "positive controls are met. Interpretation will be performed as per ISO 10993-5."
        ),
        "data_compilation": (
            "Data will be summarized in tabular form showing, for each extract and dilution, the morphological reactivity "
            "grade, the mean absorbance, the calculated cell viability (%), the results of the blank, negative and positive "
            "controls and a description of any other observation."
        ),
        "welfare": [
            "This is an in vitro study; no live animals are used. The use of an in vitro cell culture system contributes to "
            "the replacement of animal experimentation.",
            "The test facility is certified by the Republic of Türkiye Ministry of Agriculture and Forestry, General Directorate "
            "of Food and Control for animal experimentation (Certification No. – 203); this certification is not applicable to "
            "the present in vitro study.",
        ],
        "hadyek": (
            "HADYEK (local ethics committee) approval is not applicable to this study since no live animals are used "
            "(in vitro cell culture system)."
        ),
        "test_system": {
            "Species": "Mouse (Mus musculus) — established cell line (in vitro)",
            "Breed/Strain": "L929 (mammalian fibroblast cell line)",
            "Source": "Certified cell bank / culture collection (details will be provided in the raw data)",
            "Body weight at the time of dosing": "Not applicable (in vitro cell culture system)",
            "Age at the time of dosing": "Not applicable (cell passage number will be recorded)",
            "Sex": "Not applicable",
            "Number of Groups": "Test item extract, blank (vehicle) control, negative control and positive control",
            "Number of animals": "In Vitro Cell Culture System - Not Applicable for Live Animals (replicate wells per extract as per protocol)",
            "Acclimatization": "Not applicable. Cells will be maintained and sub-cultured in a CO2 incubator (37 °C, 5% CO2) and used in the exponential growth phase.",
        },
        "housing": {
            "Location": "Cell culture laboratory — CO2 Incubator (EQ-INC-001)",
            "Temperature": "37 ± 1 °C (CO2 Incubator, 5% CO2)",
            "Relative Humidity": "Humidified atmosphere",
            "Photo period": "Not applicable",
            "Room air exchanges": "Not applicable (aseptic work in a laminar flow cabinet)",
            "Caging": "In Vitro Cell Culture System - Not Applicable for Live Animals. Cells will be cultured in sterile culture plates in a CO2 incubator at 37 °C with 5% CO2.",
            "Method of identification": "Plates and wells will be labelled with the study number and extract / control identification as per the Nanolab SOP.",
            "Diet and water": "Cell culture medium supplemented with serum and antibiotics as per SOP (no animal diet is applicable).",
            "Note:": "Note: Culture medium, serum and reagents are qualified lots; lot numbers will be recorded in the raw data.",
        },
        "report_lines": {
            "Vehicle: justification of choice of vehicle.": "Extraction vehicle (culture medium): justification of choice.",
            "Test animal": "Test system",
            "Species / strain used.": "Cell line used (L929) and passage number.",
            "Number, age and sex of animals.": "Culture plate format and number of replicate wells.",
            "Source, housing conditions, diet etc.": "Cell source, culture medium, serum and incubation conditions (CO2 incubator, 37 °C, 5% CO2).",
            "Technique of injection site preparation;": "Details of cell seeding and culture preparation;",
            "Details of injection technique;": "Details of the exposure method (extract incubation period);",
            "Details of test substance preparation, application;": "Details of test item extraction (medium, ratio, temperature, duration);",
            "Details of food and water quality (including diet type/source, water source).": "Details of culture medium and reagents (type, source, lot numbers).",
            "Positive Control Response Validation:": "Control results:",
            "A summary of the results of the latest Positive Control Response Validation including information on substance, concentration and vehicle used.":
                "Results of the blank, negative and positive controls and acceptance criteria.",
            "Grading system;": "Reactivity grading system and MTT viability criteria;",
            "Grading of Intracutaneous reaction.": "Morphological reactivity grades and cell viability (%) for each extract.",
            "Signs of toxicity including mortality.": "Description of any morphological changes in the cultures.",
            "Tabulation of mean body weight and body weight change.": "Tabulation of mean absorbance values and cell viability (%).",
            "Individual weights of animals on the day of test item application, at the end of the experiment.": "Individual well absorbance values.",
        },
    },
    # ------------------------------------------------------------------ ISO 10993-10
    "ISO_10993_10_SENS": {
        "part_phrase": "Part 10 Tests for Skin Sensitization",
        "reference": (
            "International Standard ISO 10993-10:2021 Biological Evaluation of Medical Devices — Part 10 Tests for Skin "
            "Sensitization"
        ),
        "objective": (
            "The objective of this study is to evaluate the potential of the polar and non-polar extracts of the test item, "
            "{TEST_ITEM}, to cause delayed-type (type IV) skin sensitization in albino guinea pigs using the Guinea Pig "
            "Maximization / closed-patch sensitization method, comprising induction and challenge phases, in accordance with "
            "ISO 10993-10."
        ),
        "sections": {
            H_VEHICLE: (
                None,
                "Suitable vehicle will be selected before initiation of the experiment. Vehicle details and justification will be "
                "provided in the raw data and final report. However, as per International Standard ISO 10993-12 “Sample "
                "Preparation and Reference Materials”, the {POLAR} and {NONPOLAR} extraction vehicles (normal saline and a "
                "vegetable oil such as cottonseed oil) can be used. Freund's Complete Adjuvant (FCA) and the vehicle will be "
                "used in the induction phase as described in ISO 10993-10.",
            ),
            H_POSCTRL: (
                None,
                "A concurrent positive control has not been included in this study, as the sensitivity and reliability of the test "
                "system is verified periodically using a known sensitizer in a separate reliability study. The positive control "
                "results will be incorporated in the study report.",
            ),
            H_JUSTIF: (
                None,
                "Guinea pigs were chosen as the test system because this species is the most commonly used and best-characterized "
                "model for skin sensitization testing of medical device extracts. The Guinea Pig Maximization / closed-patch "
                "method is accepted by ISO 10993-10 Biological Evaluation of Medical Devices — Part 10 Tests for Skin "
                "Sensitization and meets the requirements of most regulatory agencies.",
            ),
            H_EXTRACT: (
                None,
                "Preparation of the test item extract for the {TITLE} of {TEST_ITEM} according to {STANDARD} will be conducted at "
                "the sponsor's request, in accordance with ISO 10993-12 “Sample Preparation and Reference Materials”. The "
                "extraction process will be carried out using {POLAR} and {NONPOLAR} solvents at a ratio of {RATIO}, at {TEMP} °C "
                "for {HOURS} hours in a shaking water bath. The condition of the test extract (e.g., color, clarity, and presence "
                "of any particulates) will also be described in the report. All materials and equipment required for the test "
                "meet the requirements of the relevant standards, and their suitability will be verified prior to the study.",
            ),
            H_SITE: (
                "Preparation of Animals and Test Sites",
                "Approximately 24 hours before each application, fur on the dorso-scapular region of the animals will be removed "
                "by clipping closely using an electric hair clipper (and, where required, by depilation before the challenge "
                "phase). Care will be taken to avoid abrasion of the skin; animals with healthy intact skin will be used.",
            ),
            H_ROUTE: (
                None,
                "In the induction phase, the extracts of the test item and the respective controls will be applied by intradermal "
                "injection (with or without Freund's Complete Adjuvant) and by topical occlusive patch application; in the "
                "challenge phase, topical closed-patch application will be used, as per ISO 10993-10. These routes are justified "
                "as they maximize the sensitization response and are the methods described in the guideline.",
            ),
            H_DOSE: (
                None,
                "The test item will be tested using undiluted polar and non-polar extracts that represent the chemical "
                "characteristics of the product, consistent with ISO 10993-10 and ISO 10993-12 (extraction conditions). Where "
                "required by the guideline, a preliminary irritation test will be performed to determine suitable concentrations "
                "for the induction and challenge applications. The use of undiluted extracts constitutes a scientifically and "
                "technically justified approach for the evaluation of the sensitization potential of medical devices.",
            ),
            H_ADMIN: (
                "Induction and Challenge Phases",
                "Induction phase: test animals will receive intradermal injections of the test item extracts (with Freund's "
                "Complete Adjuvant as applicable) followed by topical occlusive patch application at the induction site; control "
                "animals will be treated identically with the respective solvent controls only. A rest period as defined in ISO "
                "10993-10 will be allowed between induction and challenge. Challenge phase: test and control animals will be "
                "challenged by closed-patch application of the test item extracts and solvent controls on a naive (previously "
                "untreated) skin site; the patches will be removed after approximately 24 hours and the sites will be scored 24 "
                "and 48 hours after patch removal. The detailed application schedule will be recorded in the raw data.",
            ),
            H_OBS: (
                "Skin Reactions (Erythema and Oedema)",
                "The challenge sites will be observed 24 (±2) and 48 (±2) hours after removal of the challenge patches. Skin "
                "reactions will be graded using the Magnusson & Kligman scale given below and the observations will be recorded "
                "in the raw data and reported in the study report. Reactions in test animals will be compared with those of the "
                "control animals.",
            ),
            H_BW: (
                None,
                "The individual animal body weight will be recorded at receipt, prior to initiation of the induction phase (Day 0) "
                "and at termination of the observation period.",
            ),
        },
        "grading": {
            "title": "Magnusson & Kligman Grading Scale for Skin Reactions (ISO 10993-10)",
            "headers": ["Patch test reaction", "Grading scale"],
            "rows": [
                ["No visible change", "0"],
                ["Discrete or patchy erythema", "1"],
                ["Moderate and confluent erythema", "2"],
                ["Intense erythema and swelling", "3"],
            ],
            "footnote": (
                "A grade of 1 or greater in the test group generally indicates sensitization, provided that grades of less than 1 "
                "are observed in control animals; if grades of 1 or greater are noted in control animals, responses of test "
                "animals that exceed the most severe control reaction are considered to indicate sensitization. Other adverse "
                "changes shall be recorded and reported."
            ),
        },
        "statistics": (
            "The skin reaction grades (erythema and oedema) recorded at 24 and 48 hours after removal of the challenge patches "
            "will be evaluated for each animal in the test and control groups using the Magnusson & Kligman scale. The test "
            "item will be considered a non-sensitizer if the responses in the test group are less than grade 1 (or do not "
            "exceed the most severe response in the control group). Statistical methods are not applicable as interpretation "
            "will be performed as per ISO 10993-10."
        ),
        "data_compilation": (
            "Data will be summarized in tabular form showing, for each group, the number of animals used, the individual skin "
            "reaction grades at each observation time, the number of animals displaying signs of toxicity, the number of animals "
            "found dead or sacrificed for humane reasons (if any), description, course of toxic effects and reversibility."
        ),
        "test_system": {
            "Species": "Guinea pig (Cavia porcellus)",
            "Breed/Strain": "Albino guinea pig (e.g., Dunkin-Hartley)",
            "Body weight at the time of dosing": "Between 300 and 500 g",
            "Number of Groups": "2 (test group and control group)",
            "Number of animals": "Test group: at least 10 animals; control group: at least 5 animals (as per ISO 10993-10; final numbers will be confirmed by the Study Director; {CAGES} cages planned)",
        },
        "housing": {
            "Location": "Guinea Pig Room",
            "Temperature": "20-24 °C",
            "Caging": "The animals will be housed in cages suitable for guinea pigs with appropriate bedding as per the Nanolab SOP.",
            "Diet and water": "Guinea pig pellet diet (vitamin C supplemented) and RO water will be provided ad libitum.",
        },
        "report_lines": {
            "Technique of injection site preparation;": "Technique of application site preparation (clipping / depilation);",
            "Details of injection technique;": "Details of induction (intradermal and topical) and challenge application techniques;",
            "Details of test substance preparation, application;": "Details of test item extract preparation and application;",
            "Positive Control Response Validation:": "Positive control (known sensitizer) reliability check:",
            "A summary of the results of the latest Positive Control Response Validation including information on substance, concentration and vehicle used.":
                "A summary of the results of the latest positive control reliability check including substance, concentration and vehicle used.",
            "Grading system;": "Magnusson & Kligman grading system;",
            "Grading of Intracutaneous reaction.": "Grading of skin reactions at 24 and 48 hours after patch removal.",
        },
    },
    # ------------------------------------------------------------------ ISO 10993-11
    "ISO_10993_11_ACUTE": {
        "part_phrase": "Part 11 Tests for Systemic Toxicity",
        "reference": (
            "International Standard ISO 10993-11:2017 Biological Evaluation of Medical Devices — Part 11 Tests for Systemic "
            "Toxicity"
        ),
        "objective": (
            "The objective of this study is to evaluate the potential of the polar and non-polar extracts of the test item, "
            "{TEST_ITEM}, to cause acute systemic toxicity in rodents following a single intravenous (polar extract) or "
            "intraperitoneal (non-polar extract) administration, by observing clinical signs and body weight changes at 4, 24, "
            "48 and 72 hours after administration, in accordance with ISO 10993-11."
        ),
        "sections": {
            H_VEHICLE: (
                None,
                "Suitable vehicle will be selected before initiation of the experiment. Vehicle details and justification will be "
                "provided in the raw data and final report. However, as per International Standard ISO 10993-12 “Sample "
                "Preparation and Reference Materials”, the {POLAR} extraction vehicle (normal saline; intravenous administration) "
                "and the {NONPOLAR} extraction vehicle (vegetable oil such as cottonseed oil; intraperitoneal administration) can "
                "be used. Vehicle controls will be administered by the same route and at the same volume.",
            ),
            H_POSCTRL: (
                None,
                "A concurrent positive control is not included in this study; the validity of the test is demonstrated by the "
                "concurrent vehicle (solvent) control animals treated by the same route and volume, together with the historical "
                "data of the test facility.",
            ),
            H_JUSTIF: (
                None,
                "Rodents (Mouse/Rat Room) were chosen as the test system because this group of species is commonly used and "
                "recommended by ISO 10993-11 for the acute systemic toxicity testing of medical device extracts. The routes are "
                "intravenous (polar extract) and intraperitoneal (non-polar extract), which ensure systemic distribution of the "
                "leachable substances and meet the requirements of most regulatory agencies according to ISO 10993-11 Biological "
                "Evaluation of Medical Devices — Part 11 Tests for Systemic Toxicity.",
            ),
            H_EXTRACT: (None, _EXTRACT_ANIMAL),
            H_SITE: (
                "Animal Preparation and Randomization",
                "Animals will be weighed and randomly allocated to the test and control groups before administration. Animals "
                "with any evidence of ill health will be excluded from the study.",
            ),
            H_ROUTE: (
                None,
                "The polar extract of the test item and the respective polar vehicle control will be administered intravenously "
                "(e.g., via the lateral tail vein), and the non-polar extract and the respective non-polar vehicle control will "
                "be administered intraperitoneally, as per ISO 10993-11. These routes are justified since they provide systemic "
                "exposure to the leachable substances of the test item.",
            ),
            H_DOSE: (
                None,
                "The test item will be evaluated using undiluted polar and non-polar extracts at the dose volumes recommended in "
                "ISO 10993-11 (e.g., 50 mL/kg body weight, not exceeding the maximum volume allowed for the route of "
                "administration). The dose volumes will be calculated from the body weight of each animal on the day of "
                "administration and recorded in the raw data.",
            ),
            H_ADMIN: (
                None,
                "On the day of treatment, each animal of the test groups will receive a single injection of the respective test "
                "item extract and each animal of the control groups a single injection of the respective vehicle, by the routes "
                "described above. Animals will be observed immediately after administration and at 4, 24, 48 and 72 hours after "
                "administration.",
            ),
            H_OBS: (
                "Clinical Observations at 4, 24, 48 and 72 Hours",
                "Animals will be observed immediately after injection and at 4, 24, 48 and 72 hours after injection for clinical "
                "signs of toxicity (changes in skin, fur, eyes, mucous membranes, respiratory, circulatory, autonomic and central "
                "nervous systems, somatomotor activity and behaviour pattern; tremors, convulsions, salivation, diarrhoea, "
                "lethargy, coma) and mortality. The observations will be recorded in the raw data and reported in the study "
                "report.",
            ),
            H_BW: (
                None,
                "The individual animal body weight will be recorded before administration (Day 0 of treatment) and at 24, 48 and "
                "72 hours after administration, and the body weight change will be calculated.",
            ),
            H_EUTH: (
                "Euthanasia and Necropsy",
                "At the end of the 72-hour observation period, surviving animals will be euthanized as per standard procedures; "
                "animals found dead or euthanized for humane reasons during the study will be subjected to gross necropsy where "
                "applicable. If any animal gets injured, ill or moribund, care will be taken as per current veterinary practices "
                "and the sponsor will be informed.",
            ),
        },
        "grading": {
            "title": "Observation Schedule and Parameters (ISO 10993-11)",
            "headers": ["Time after administration", "Observations"],
            "rows": [
                ["Immediately and 4 hours", "Clinical signs of toxicity and mortality"],
                ["24 hours", "Clinical signs, mortality and body weight"],
                ["48 hours", "Clinical signs, mortality and body weight"],
                ["72 hours", "Clinical signs, mortality, body weight and terminal observations"],
            ],
            "footnote": (
                "Evaluation criteria will be applied as defined in ISO 10993-11 (including repeat-testing provisions where "
                "applicable). Other adverse changes shall be recorded and reported."
            ),
        },
        "statistics": (
            "The clinical observations and body weights of the animals treated with the test item extracts will be compared "
            "with those of the respective vehicle control animals at each observation time. The test item will be evaluated per "
            "the criteria of ISO 10993-11 (mortality, clinical signs and body weight loss). Statistical methods are not "
            "applicable as interpretation will be performed as per ISO 10993-11."
        ),
        "data_compilation": (
            "Data will be summarized in tabular form showing, for each group, the number of animals used, the number of animals "
            "displaying signs of toxicity, the number of animals found dead during the test or sacrificed for humane reasons (if "
            "any), individual body weights and body weight changes, description, course of toxic effects and reversibility."
        ),
        "test_system": {
            "Species": "Mouse (Mus musculus) / Rat (Rattus norvegicus) — rodent species to be confirmed in the final protocol",
            "Breed/Strain": "Albino Swiss mouse (or as specified in the final protocol)",
            "Body weight at the time of dosing": "Mice: approximately 17–25 g (rats as specified in the final protocol)",
            "Sex": "Male or female (nulliparous and non-pregnant); one sex per group",
            "Number of Groups": "4 (polar extract, polar vehicle control, non-polar extract, non-polar vehicle control)",
            "Number of animals": "Typically 5 animals per group as per ISO 10993-11 (final numbers will be confirmed by the Study Director; {CAGES} cages planned)",
        },
        "housing": {
            "Location": "Mouse / Rat Room",
            "Temperature": "20-24 °C",
            "Caging": "The animals will be housed in polycarbonate cages with appropriate bedding as per the Nanolab SOP (group housing by treatment group).",
            "Diet and water": "Standard laboratory rodent pellet diet and RO water will be provided ad libitum.",
        },
        "report_lines": {
            "Technique of injection site preparation;": "Technique of injection preparation (intravenous / intraperitoneal);",
            "Details of injection technique;": "Details of intravenous and intraperitoneal injection techniques and dose volumes;",
            "Positive Control Response Validation:": "Vehicle control groups:",
            "A summary of the results of the latest Positive Control Response Validation including information on substance, concentration and vehicle used.":
                "Results of the vehicle control animals treated by the same route and volume.",
            "Grading system;": "Clinical observation parameters and evaluation criteria;",
            "Grading of Intracutaneous reaction.": "Clinical observations at 4, 24, 48 and 72 hours.",
        },
    },
    # ------------------------------------------------------------------ ISO 10993-11 / USP 151 Pyrogenicity
    "ISO_10993_11_PYRO": {
        "part_phrase": "Part 11 Tests for Systemic Toxicity — Material-Mediated Pyrogenicity (USP <151>)",
        "reference": "International Standard ISO 10993-11:2017 & United States Pharmacopeia USP <151> Pyrogen Test",
        "objective": (
            "The objective of this study is to evaluate the potential of the polar extract of the test item, {TEST_ITEM}, "
            "to induce a material-mediated pyrogenic response (febrile temperature rise) in New Zealand White rabbits "
            "following intravenous administration in accordance with ISO 10993-11 and USP <151>."
        ),
        "sections": {
            H_EXTRACT: (None, _EXTRACT_ANIMAL),
            H_ROUTE: (
                None,
                "The polar extract (0.9% sterile pyrogen-free NaCl) of the test item will be warmed to 37 ± 2 °C and "
                "administered intravenously via the marginal ear vein at a dose volume of 10 mL/kg body weight in accordance "
                "with USP <151> and ISO 10993-11.",
            ),
            H_OBS: (
                "Rectal Temperature Measurements (1, 2 and 3 Hours)",
                "Baseline rectal temperature (control temperature) will be recorded prior to injection. Following intravenous "
                "injection, rectal temperatures will be recorded at 1, 2 and 3 hours post-injection. An individual temperature "
                "rise of < 0.5 °C in all 3 rabbits meets the requirements for absence of pyrogenicity.",
            ),
        },
        "test_system": {
            "Species": "Rabbit (Oryctolagus cuniculus)",
            "Breed/Strain": "New Zealand White",
            "Number of animals": "3 to 5 animals ({CAGES} cages planned; reuse subject to veterinary & HADYEK approval)",
        },
        "housing": _RABBIT_HOUSING,
    },
    # ------------------------------------------------------------------ ISO 10993-4 Hemolysis
    "ISO_10993_4_HEMO": {
        "part_phrase": "Part 4 Selection of Tests for Interactions with Blood (Hemolysis)",
        "reference": "International Standard ISO 10993-4:2017 & ASTM F756 Standard Practice for Assessment of Hemolytic Properties of Materials",
        "objective": (
            "The objective of this study is to evaluate the hemolytic potential of the test item, {TEST_ITEM}, on rabbit "
            "erythrocytes by direct contact and extract methods in accordance with ISO 10993-4 and ASTM F756."
        ),
        "sections": {
            H_EXTRACT: (None, _EXTRACT_ANIMAL),
            H_OBS: (
                "Spectrophotometric Determination of Hemolytic Index",
                "Following incubation with diluted rabbit blood at 37 ± 1 °C, hemoglobin release in the supernatant will be "
                "determined spectrophotometrically at 540 nm and the hemolytic index (%) will be calculated relative to "
                "negative and positive controls.",
            ),
        },
        "test_system": {
            "Species": "Rabbit (Oryctolagus cuniculus) — anticoagulated donor blood",
            "Breed/Strain": "New Zealand White",
            "Number of animals": "3 donor rabbits ({CAGES} cage planned)",
        },
        "housing": _RABBIT_HOUSING,
    },
    # ------------------------------------------------------------------ PHYS_CHEM_MONO
    "PHYS_CHEM_MONO": {
        "part_phrase": "Pharmacopoeial Physical-Chemical Monograph Analysis (Non-GLP)",
        "reference": "European Pharmacopoeia (EP) / United States Pharmacopeia (USP) Relevant Monograph",
        "objective": (
            "The objective of this study is to perform physical and chemical quality control / monograph analysis of the test "
            "item, {TEST_ITEM}, in accordance with the relevant pharmacopoeial monograph and Nanolab analytical SOPs."
        ),
        "sections": {},
        "test_system": {
            "Species": "Not applicable (Analytical / Physical-Chemical testing — Non-GLP)",
            "Number of animals": "0 (No live animals used)",
        },
        "housing": {
            "Location": "Physical-Chemical Analytical Laboratory",
            "Caging": "Not applicable (Analytical testing)",
        },
    },
}

# Türev şablonlar ana şablon metinlerini miras alır
TEMPLATE_CONTENT["ISO_10993_11_SUBACUTE"] = dict(
    TEMPLATE_CONTENT["ISO_10993_11_ACUTE"],
    objective=(
        "The objective of this study is to evaluate the potential subacute systemic toxicity of the test item, {TEST_ITEM}, "
        "in rodents following repeated administration/exposure over 14/28 days, including clinical observations, body weight, "
        "hematology, clinical biochemistry, gross necropsy and histopathology in accordance with ISO 10993-11."
    ),
)
TEMPLATE_CONTENT["ISO_10993_11_SUBCHRONIC"] = dict(
    TEMPLATE_CONTENT["ISO_10993_11_ACUTE"],
    objective=(
        "The objective of this study is to evaluate the potential subchronic (90-day) systemic toxicity of the test item, "
        "{TEST_ITEM}, in rodents following 90-day exposure, including weekly clinical and body weight observations, "
        "hematology, clinical biochemistry, organ weights, gross necropsy and histopathology in accordance with ISO 10993-11."
    ),
)
TEMPLATE_CONTENT["ISO_10993_6_IMP_13W"] = dict(
    TEMPLATE_CONTENT["ISO_10993_6_IMP"],
    objective=(
        "The objective of this study is to evaluate the local biological tissue response to the test item, {TEST_ITEM}, "
        "following 13-week (3-month) implantation in accordance with ISO 10993-6."
    ),
)
TEMPLATE_CONTENT["ISO_10993_6_IMP_26W"] = dict(
    TEMPLATE_CONTENT["ISO_10993_6_IMP"],
    objective=(
        "The objective of this study is to evaluate the local biological tissue response to the test item, {TEST_ITEM}, "
        "following 26-week (6-month) long-term implantation in accordance with ISO 10993-6."
    ),
)
