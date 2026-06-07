import unittest


class ProzorroAnalysisTests(unittest.TestCase):
    def flag_types(self, analysis):
        return [flag["type"] for flag in analysis.risk_flags]

    def assertFlagTypes(self, analysis, expected):
        self.assertEqual(self.flag_types(analysis), expected)
        for flag in analysis.risk_flags:
            self.assertEqual(flag["source"], "prozorro_analysis")
            self.assertEqual(flag["status"], "found")
            self.assertEqual(flag["confidence"], "medium")
            self.assertEqual(flag["match_type"], "positive_match")
            self.assertTrue(flag["raw_text"])
            self.assertTrue(flag["matched_pattern"])

    def test_empty_or_unavailable_data_adds_no_risk(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(None)

        self.assertEqual(analysis.status, "not_found")
        self.assertEqual(analysis.stats.procurements_count, 0)
        self.assertEqual(analysis.risk_flags, [])
        self.assertIn("Prozorro-дані відсутні або не передані", analysis.summary)

    def test_participations_without_wins_adds_note_but_no_risk(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            [
                {"id": "UA-1", "participated": True, "won": False, "date": "2025-01-10"},
                {"id": "UA-2", "participated": True, "won": False, "date": "2025-02-10"},
                {"id": "UA-3", "participated": True, "won": False, "date": "2025-03-10"},
            ]
        )

        self.assertEqual(analysis.status, "found")
        self.assertEqual(analysis.stats.procurements_count, 3)
        self.assertEqual(analysis.stats.participations_count, 3)
        self.assertEqual(analysis.stats.wins_count, 0)
        self.assertEqual(analysis.stats.win_rate_percent, 0.0)
        self.assertEqual(self.flag_types(analysis), [])
        self.assertTrue(any("перемог не має" in note for note in analysis.info_notes))
        self.assertTrue(any("Сам факт участі не є ризиком" in note for note in analysis.info_notes))

    def test_raw_aliases_are_normalized(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            {
                "items": [
                    {
                        "tender_id": "UA-ALIAS-1",
                        "name": "Поставка паперу",
                        "classification_id": "30190000-7",
                        "procuring_entity": "Школа N1",
                        "buyer_identifier": "11111111",
                        "value": "100000",
                        "proposal_value": "90000",
                        "award_value": "90000",
                        "participants_count": "2",
                        "participated": True,
                        "won": True,
                        "has_contract": True,
                        "contract_completed": True,
                        "award_date": "2025-05-10",
                    }
                ]
            }
        )

        procurement = analysis.procurements[0]
        self.assertEqual(procurement.procurement_id, "UA-ALIAS-1")
        self.assertEqual(procurement.title, "Поставка паперу")
        self.assertEqual(procurement.cpv_code, "30190000-7")
        self.assertEqual(procurement.buyer_name, "Школа N1")
        self.assertEqual(procurement.buyer_edrpou, "11111111")
        self.assertEqual(procurement.expected_value_uah, 100000.0)
        self.assertEqual(procurement.bid_value_uah, 90000.0)
        self.assertEqual(procurement.contract_value_uah, 90000.0)
        self.assertEqual(procurement.participants_count, 2)
        self.assertEqual(analysis.stats.wins_count, 1)
        self.assertEqual(analysis.stats.completed_contracts_count, 1)

    def test_one_terminated_contract_adds_single_termination_risk(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            [
                {
                    "id": "UA-TERM-1",
                    "participated": True,
                    "won": True,
                    "has_contract": True,
                    "contract_terminated": True,
                    "termination_reason": "Contract terminated by agreement.",
                },
                {"id": "UA-OK-1", "participated": True, "won": True, "has_contract": True},
                {"id": "UA-OK-2", "participated": True, "won": True, "has_contract": True},
                {"id": "UA-OK-3", "participated": True, "won": True, "has_contract": True},
            ]
        )

        self.assertFlagTypes(analysis, ["prozorro_termination_found"])

    def test_terminated_contract_without_has_contract_adds_termination_risk(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            [
                {
                    "id": "UA-TERM-1",
                    "participated": True,
                    "won": True,
                    "contract_terminated": True,
                    "termination_reason": "Contract terminated by agreement.",
                },
                {"id": "UA-OK-1", "participated": True, "won": True, "has_contract": True},
                {"id": "UA-OK-2", "participated": True, "won": True, "has_contract": True},
                {"id": "UA-OK-3", "participated": True, "won": True, "has_contract": True},
            ]
        )

        self.assertEqual(analysis.stats.contracts_count, 4)
        self.assertEqual(analysis.stats.terminated_contracts_count, 1)
        self.assertFlagTypes(analysis, ["prozorro_termination_found"])

    def test_two_terminated_contracts_add_multiple_terminations_risk(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            [
                {
                    "id": "UA-TERM-1",
                    "participated": True,
                    "won": True,
                    "has_contract": True,
                    "contract_terminated": True,
                    "termination_reason": "Contract terminated by agreement.",
                },
                {
                    "id": "UA-TERM-2",
                    "participated": True,
                    "won": True,
                    "has_contract": True,
                    "contract_terminated": True,
                    "termination_reason": "Contract terminated by agreement.",
                },
            ]
        )

        self.assertFlagTypes(
            analysis,
            ["prozorro_termination_found", "multiple_prozorro_terminations_found"],
        )

    def test_refusal_to_supply_and_deadline_breach_add_nonperformance_risk(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            [
                {
                    "id": "UA-TERM-1",
                    "participated": True,
                    "won": True,
                    "has_contract": True,
                    "contract_terminated": True,
                    "termination_reason": "Supplier refusal to supply goods and deadline breach.",
                },
                {
                    "id": "UA-OK-1",
                    "participated": True,
                    "won": True,
                    "has_contract": True,
                    "contract_completed": True,
                },
                {"id": "UA-OK-2", "participated": True, "won": True, "has_contract": True},
                {"id": "UA-OK-3", "participated": True, "won": True, "has_contract": True},
            ]
        )

        self.assertFlagTypes(
            analysis,
            ["prozorro_termination_found", "contract_nonperformance_case"],
        )

    def test_quality_related_termination_reason_adds_nonperformance_risk(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            [
                {
                    "id": "UA-TERM-1",
                    "participated": True,
                    "won": True,
                    "has_contract": True,
                    "contract_terminated": True,
                    "termination_reason": "неналежна якість поставки",
                },
                {"id": "UA-OK-1", "participated": True, "won": True, "has_contract": True},
                {"id": "UA-OK-2", "participated": True, "won": True, "has_contract": True},
                {"id": "UA-OK-3", "participated": True, "won": True, "has_contract": True},
            ]
        )

        self.assertFlagTypes(
            analysis,
            ["prozorro_termination_found", "contract_nonperformance_case"],
        )

    def test_neutral_quality_requirement_change_does_not_add_nonperformance_risk(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            [
                {
                    "id": "UA-TERM-1",
                    "participated": True,
                    "won": True,
                    "has_contract": True,
                    "contract_terminated": True,
                    "termination_reason": "contract terminated due to changed quality requirements",
                },
                {"id": "UA-OK-1", "participated": True, "won": True, "has_contract": True},
                {"id": "UA-OK-2", "participated": True, "won": True, "has_contract": True},
                {"id": "UA-OK-3", "participated": True, "won": True, "has_contract": True},
            ]
        )

        self.assertFlagTypes(analysis, ["prozorro_termination_found"])

    def test_frequent_disqualifications_are_flagged_by_count_or_rate(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        count_analysis = analyze_prozorro_data(
            [
                {"id": "UA-DQ-1", "participated": True, "disqualified": True},
                {"id": "UA-DQ-2", "participated": True, "disqualified": True},
                {"id": "UA-DQ-3", "participated": True, "disqualified": True},
                {"id": "UA-OK-1", "participated": True},
            ]
        )
        rate_analysis = analyze_prozorro_data(
            [
                {"id": "UA-DQ-1", "participated": True, "disqualified": True},
                {"id": "UA-DQ-2", "participated": True, "disqualified": True},
                {"id": "UA-OK-1", "participated": True},
            ]
        )

        self.assertIn("frequent_prozorro_disqualifications", self.flag_types(count_analysis))
        self.assertIn("frequent_prozorro_disqualifications", self.flag_types(rate_analysis))

    def test_disqualification_reasons_map_to_risk_flags(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        cases = [
            ("tax debt is present", "tax_debt_found"),
            ("large tax debt is present", "large_tax_debt_found"),
            ("supplier is bankrupt", "bankruptcy_found"),
            ("supplier is under sanctions", "sanctions_found"),
            ("problematic documents were submitted", "problematic_documents_found"),
            ("qualification mismatch with tender requirements", "qualification_mismatch_found"),
        ]

        for reason, expected in cases:
            with self.subTest(reason=reason):
                analysis = analyze_prozorro_data(
                    [{"id": "UA-DQ-1", "disqualified": True, "disqualification_reason": reason}]
                )

                self.assertFlagTypes(analysis, [expected])

    def test_clear_medical_cpv_kved_mismatch_adds_risk(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            [
                {"id": "UA-MED-1", "title": "Лабораторне обладнання", "cpv": "33100000-1"},
                {"id": "UA-MED-2", "name": "Медичні вироби", "cpv": "38000000-5"},
                {"id": "UA-MED-3", "title": "Медичні матеріали", "cpv": "33140000-3"},
            ],
            company_context={
                "main_activity_name": "Оптова торгівля паливом",
                "additional_activities": [],
            },
        )

        self.assertIn("kved_mismatch", self.flag_types(analysis))

    def test_uncertain_cpv_kved_matching_adds_note_but_no_risk(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            [{"id": "UA-GEN-1", "title": "Послуги", "cpv_name": "Різні послуги"}],
            company_context={"main_activity_name": "Неспеціалізована оптова торгівля"},
        )

        self.assertNotIn("kved_mismatch", self.flag_types(analysis))
        self.assertTrue(any("відповідність CPV" in note for note in analysis.info_notes))

    def test_single_buyer_concentration_adds_risk_and_note(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            [
                {
                    "id": f"UA-BUYER-{index}",
                    "participated": True,
                    "won": True,
                    "has_contract": True,
                    "buyer_edrpou": "12345678",
                    "contract_value": 100000,
                }
                for index in range(5)
            ]
        )

        self.assertIn("single_buyer_concentration", self.flag_types(analysis))
        self.assertTrue(any("одним замовником" in note for note in analysis.info_notes))

    def test_single_buyer_concentration_falls_back_to_buyer_name(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            [
                {
                    "id": f"UA-BUYER-NAME-{index}",
                    "participated": True,
                    "won": True,
                    "has_contract": True,
                    "buyer_name": "Департамент охорони здоров'я",
                    "contract_value": 100000,
                }
                for index in range(5)
            ]
        )

        self.assertIn("single_buyer_concentration", self.flag_types(analysis))
        self.assertTrue(any("одним замовником" in note for note in analysis.info_notes))

    def test_low_competition_wins_adds_risk(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            [
                {
                    "id": f"UA-LOW-COMP-{index}",
                    "participated": True,
                    "won": True,
                    "participants_count": 1,
                }
                for index in range(5)
            ]
        )

        self.assertIn("low_competition_wins", self.flag_types(analysis))

    def test_frequent_amendments_and_substantial_amount_increase_add_risks(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        procurements = [
            {
                "id": f"UA-CHANGES-{index}",
                "has_contract": True,
                "amendments_count": 3,
            }
            for index in range(5)
        ]
        procurements.append(
            {
                "id": "UA-INCREASE-1",
                "has_contract": True,
                "contract_amount_change_percent": 25,
            }
        )

        analysis = analyze_prozorro_data(procurements)

        self.assertIn("frequent_contract_changes", self.flag_types(analysis))
        self.assertIn("substantial_contract_amount_increase", self.flag_types(analysis))

    def test_repeated_deep_discounts_add_dumping_risk_but_isolated_discount_does_not(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        repeated_analysis = analyze_prozorro_data(
            [
                {"id": "UA-DISC-1", "expected_value": 100000, "proposal_value": 50000},
                {"id": "UA-DISC-2", "expected_value": 200000, "proposal_value": 90000},
            ]
        )
        isolated_analysis = analyze_prozorro_data(
            [{"id": "UA-DISC-1", "expected_value": 100000, "proposal_value": 50000}]
        )

        self.assertIn("possible_prozorro_dumping", self.flag_types(repeated_analysis))
        self.assertNotIn("possible_prozorro_dumping", self.flag_types(isolated_analysis))

    def test_supplier_related_complaints_add_risk_but_generic_complaints_do_not(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        supplier_analysis = analyze_prozorro_data(
            [{"id": "UA-COMPLAINT-1", "supplier_related_complaints_count": 1}]
        )
        generic_analysis = analyze_prozorro_data([{"id": "UA-COMPLAINT-2", "complaints_count": 3}])

        self.assertIn("supplier_related_prozorro_complaints", self.flag_types(supplier_analysis))
        self.assertNotIn("supplier_related_prozorro_complaints", self.flag_types(generic_analysis))

    def test_old_procurements_add_note_but_no_risk(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data([{"id": "UA-OLD-1", "participated": True, "date": "2020-01-01"}])

        self.assertEqual(self.flag_types(analysis), [])
        self.assertTrue(any("була давно" in note for note in analysis.info_notes))


if __name__ == "__main__":
    unittest.main()
