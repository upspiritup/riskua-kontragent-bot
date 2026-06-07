import unittest


class RiskScoringTests(unittest.TestCase):
    def test_calculate_final_risk_levels(self):
        from app.services.risk_scoring import calculate_final_risk

        self.assertEqual(calculate_final_risk([])["level"], "low")
        self.assertEqual(
            calculate_final_risk([{"type": "court_cases_found", "source": "opendatabot"}])["level"],
            "low",
        )
        self.assertEqual(
            calculate_final_risk([{"type": "tax_debt_found", "source": "clarity_project"}])["level"],
            "medium",
        )
        self.assertEqual(
            calculate_final_risk(
                [
                    {"type": "tax_debt_found", "source": "clarity_project"},
                    {"type": "enforcement_found", "source": "youcontrol"},
                ]
            )["level"],
            "high",
        )
        self.assertEqual(
            calculate_final_risk([{"type": "bankruptcy_found", "source": "clarity_project"}])["level"],
            "critical",
        )

    def test_calculate_final_risk_returns_score_label_and_reasons(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "tax_debt_found", "source": "clarity_project"},
                {"type": "court_cases_found", "source": "opendatabot"},
            ]
        )

        self.assertEqual(result["score"], 26)
        self.assertEqual(result["level"], "medium")
        self.assertEqual(result["label_uk"], "Середній ризик")
        self.assertEqual([reason["type"] for reason in result["reasons"]], ["tax_debt_found", "court_cases_found"])

    def test_dedupes_same_risk_flag(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "tax_debt_found", "source": "opendatabot"},
                {"type": "tax_debt_found", "source": "clarity_project"},
                {"type": "tax_debt_found", "source": "youcontrol"},
            ]
        )

        self.assertEqual(result["score"], 25)
        self.assertEqual(len(result["reasons"]), 1)
        self.assertEqual(result["reasons"][0]["type"], "tax_debt_found")
        self.assertEqual(
            result["reasons"][0]["sources"],
            ["opendatabot", "clarity_project", "youcontrol"],
        )
        self.assertEqual(result["reasons"][0]["weight"], 25)

    def test_aliases_are_normalized_to_unified_dictionary(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "enforcement_proceeding_found", "source": "clarity_project"},
                {"type": "multiple_enforcement_proceedings", "source": "clarity_project"},
                {"type": "court_mentions_found", "source": "opendatabot"},
            ]
        )

        self.assertEqual([reason["type"] for reason in result["reasons"]], ["enforcement_found", "court_cases_found"])
        self.assertEqual(result["score"], 36)

    def test_source_unavailable_has_zero_weight(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk([{"type": "source_unavailable", "source": "youcontrol"}])

        self.assertEqual(result["score"], 0)
        self.assertEqual(result["level"], "low")

    def test_tax_source_unavailable_has_zero_weight(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk([{"type": "tax_source_unavailable", "source": "tax"}])

        self.assertEqual(result["score"], 0)
        self.assertEqual(result["level"], "low")
        self.assertEqual(result["reasons"], [])

    def test_tax_specific_flags_are_known_risk_reasons(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "large_tax_debt_found", "source": "tax"},
                {"type": "vat_registration_cancelled", "source": "tax"},
            ]
        )

        self.assertEqual(
            [reason["type"] for reason in result["reasons"]],
            ["large_tax_debt_found", "vat_registration_cancelled"],
        )
        self.assertEqual(result["score"], 80)
        self.assertEqual(result["level"], "high")

    def test_website_unavailable_alone_is_not_critical(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk([{"type": "website_unavailable", "source": "domain_reputation"}])

        self.assertLess(result["score"], 50)
        self.assertNotEqual(result["level"], "critical")

    def test_domain_reputation_flags_increase_combined_risk(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "free_email_used", "source": "domain_reputation"},
                {"type": "company_edrpou_not_found_on_website", "source": "domain_reputation"},
                {"type": "suspicious_redirects", "source": "domain_reputation"},
            ]
        )

        self.assertEqual(
            [reason["type"] for reason in result["reasons"]],
            ["free_email_used", "company_edrpou_not_found_on_website", "suspicious_redirects"],
        )
        self.assertGreaterEqual(result["score"], 50)

    def test_score_is_capped_without_confirmed_hard_fact(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "free_email_used", "source": "domain_reputation"},
                {"type": "company_edrpou_not_found_on_website", "source": "domain_reputation"},
                {"type": "company_name_not_found_on_website", "source": "domain_reputation"},
                {"type": "suspicious_redirects", "source": "domain_reputation"},
                {"type": "kved_mismatch", "source": "opendatabot"},
                {"type": "young_company", "source": "opendatabot"},
            ]
        )

        self.assertEqual(result["score"], 65)
        self.assertEqual(result["level"], "high")
        self.assertFalse(result["hard_fact_present"])
        self.assertNotEqual(result["level"], "critical")

    def test_two_court_mentions_without_classified_risk_do_not_make_score_75(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk([{"type": "court_cases_found", "source": "opendatabot"}])

        self.assertLess(result["score"], 75)
        self.assertEqual(result["score"], 1)
        self.assertFalse(result["hard_fact_present"])

    def test_conflict_without_hard_fact_is_capped_at_65(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "tax_debt_found", "source": "clarity_project", "status": "found"},
                {"type": "tax_debt_found", "source": "youcontrol", "status": "not_found"},
                {"type": "free_email_used", "source": "domain_reputation"},
                {"type": "company_edrpou_not_found_on_website", "source": "domain_reputation"},
                {"type": "suspicious_redirects", "source": "domain_reputation"},
            ]
        )

        self.assertEqual(result["level"], "manual_review")
        self.assertLessEqual(result["score"], 65)
        self.assertFalse(result["hard_fact_present"])

    def test_company_not_found_hard_fact_can_reach_100(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk([{"type": "company_not_found", "source": "opendatabot"}])

        self.assertEqual(result["score"], 100)
        self.assertEqual(result["level"], "critical")
        self.assertTrue(result["hard_fact_present"])

    def test_conflicting_bankruptcy_sources_need_manual_review_and_not_100(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "bankruptcy_found", "source": "clarity_project", "status": "found", "raw_text": "Банкрутство: 1"},
                {"type": "bankruptcy_found", "source": "youcontrol", "status": "not_found", "raw_text": "Банкрутство не виявлено"},
            ]
        )

        self.assertEqual(result["level"], "manual_review")
        self.assertEqual(result["label_uk"], "Потребує ручної перевірки")
        self.assertTrue(result["manual_review_required"])
        self.assertLess(result["score"], 100)
        self.assertEqual(result["conflicts"][0]["type"], "bankruptcy_found")
        self.assertEqual(result["conflicts"][0]["found_sources"], ["clarity_project"])
        self.assertEqual(result["conflicts"][0]["not_found_sources"], ["youcontrol"])

    def test_prozorro_specific_flags_have_expected_weights(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "multiple_prozorro_terminations_found", "source": "prozorro_analysis"},
                {"type": "frequent_prozorro_disqualifications", "source": "prozorro_analysis"},
                {"type": "single_buyer_concentration", "source": "prozorro_analysis"},
            ]
        )

        self.assertEqual(
            [reason["type"] for reason in result["reasons"]],
            [
                "multiple_prozorro_terminations_found",
                "frequent_prozorro_disqualifications",
                "single_buyer_concentration",
            ],
        )
        self.assertEqual([reason["weight"] for reason in result["reasons"]], [35, 20, 15])
        self.assertEqual(result["score"], 65)

    def test_prozorro_duplicate_existing_flag_counts_once(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "tax_debt_found", "source": "prozorro_analysis"},
                {"type": "tax_debt_found", "source": "tax"},
            ]
        )

        self.assertEqual(result["score"], 25)
        self.assertEqual(len(result["reasons"]), 1)
        self.assertEqual(result["reasons"][0]["sources"], ["prozorro_analysis", "tax"])

    def test_all_new_prozorro_flags_are_known(self):
        from app.services.risk_scoring import calculate_final_risk

        flags = [
            "problematic_documents_found",
            "qualification_mismatch_found",
            "low_competition_wins",
            "frequent_contract_changes",
            "substantial_contract_amount_increase",
            "possible_prozorro_dumping",
            "supplier_related_prozorro_complaints",
        ]

        result = calculate_final_risk([{"type": flag, "source": "prozorro_analysis"} for flag in flags])

        self.assertEqual([reason["type"] for reason in result["reasons"]], flags)
        self.assertEqual([reason["weight"] for reason in result["reasons"]], [35, 20, 15, 10, 20, 10, 15])


if __name__ == "__main__":
    unittest.main()
