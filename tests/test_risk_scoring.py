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

    def test_bankruptcy_found_alone_scores_at_least_90(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk([{"type": "bankruptcy_found", "source": "opendatabot"}])

        self.assertGreaterEqual(result["score"], 90)
        self.assertEqual(result["level"], "critical")
        self.assertEqual(result["max_hard_flag_weight"], 90)

    def test_bankruptcy_with_termination_is_not_capped_below_90(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "bankruptcy_found", "source": "opendatabot"},
                {"type": "company_in_termination", "source": "opendatabot"},
            ]
        )

        self.assertGreaterEqual(result["score"], 90)

    def test_bankruptcy_with_prozorro_sale_risk_is_not_capped_to_80_or_65(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "bankruptcy_found", "source": "opendatabot"},
                {"type": "prozorro_sale_risky_auction", "source": "prozorro_sale"},
            ]
        )

        self.assertGreaterEqual(result["score"], 90)
        self.assertNotIn(result["score"], {65, 80})

    def test_strong_financial_profile_reduces_score_without_hard_negative(self):
        from app.services.risk_scoring import calculate_final_risk

        base = calculate_final_risk(
            [
                {"type": "tax_debt_found", "source": "opendatabot"},
                {"type": "court_cases_found", "source": "opendatabot"},
            ]
        )
        reduced = calculate_final_risk(
            [
                {"type": "tax_debt_found", "source": "opendatabot"},
                {"type": "court_cases_found", "source": "opendatabot"},
                {"type": "strong_financial_profile", "source": "financials"},
            ]
        )

        self.assertEqual(base["score"], 26)
        self.assertEqual(reduced["positive_financial_reducer"], 8)
        self.assertEqual(reduced["score"], 18)
        self.assertIn("strong_financial_profile", reduced["applied_flags"])

    def test_very_strong_financial_profile_is_blocked_by_bankruptcy(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "bankruptcy_found", "source": "opendatabot"},
                {"type": "very_strong_financial_profile", "source": "financials"},
            ]
        )

        self.assertEqual(result["positive_financial_reducer"], 0)
        self.assertGreaterEqual(result["score"], 90)
        self.assertIn("very_strong_financial_profile", result["applied_flags"])

    def test_financial_reducer_does_not_lower_significant_debt_below_50(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "large_tax_debt_found", "source": "tax"},
                {"type": "many_court_mentions_found", "source": "opendatabot"},
                {"type": "very_strong_financial_profile", "source": "financials"},
            ]
        )

        self.assertEqual(result["positive_financial_reducer"], 15)
        self.assertEqual(result["positive_financial_reducer_floor"], 50)
        self.assertEqual(result["score"], 50)

    def test_strong_financial_profile_with_no_information_flags_keeps_minimum_score(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk([{"type": "strong_financial_profile", "source": "financials"}])

        self.assertEqual(result["score"], 5)
        self.assertEqual(result["information_floor"], 0)
        self.assertEqual(result["score_after_reducer"], 0)
        self.assertEqual(result["minimum_score_floor"], 5)

    def test_no_flags_keeps_minimum_score(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk([])

        self.assertEqual(result["score"], 5)
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["minimum_score_floor"], 5)

    def test_strong_financial_profile_with_many_court_mentions_has_information_floor(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "many_court_mentions_found", "source": "opendatabot"},
                {"type": "very_strong_financial_profile", "source": "financials"},
            ]
        )

        self.assertEqual(result["positive_financial_reducer"], 15)
        self.assertEqual(result["score_after_reducer"], 0)
        self.assertEqual(result["information_floor"], 5)
        self.assertEqual(result["score"], 5)
        self.assertEqual(result["level"], "low")

    def test_several_court_mentions_score_above_single_document_noise(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "court_cases_found", "source": "opendatabot"},
                {"type": "several_court_mentions_found", "source": "opendatabot"},
            ]
        )

        self.assertEqual(result["score"], 8)
        self.assertEqual(result["level"], "low")

    def test_strong_financial_profile_with_very_many_court_mentions_has_higher_information_floor(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "many_court_mentions_found", "source": "opendatabot"},
                {"type": "very_many_court_mentions_found", "source": "opendatabot"},
                {"type": "very_strong_financial_profile", "source": "financials"},
            ]
        )

        self.assertEqual(result["score_after_reducer"], 0)
        self.assertEqual(result["information_floor"], 8)
        self.assertEqual(result["score"], 8)

    def test_strong_financial_profile_with_prozorro_sale_debtor_mention_has_information_floor(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "prozorro_sale_debtor_mention", "source": "prozorro_sale"},
                {"type": "very_strong_financial_profile", "source": "financials"},
            ]
        )

        self.assertEqual(result["score_after_reducer"], 0)
        self.assertEqual(result["information_floor"], 3)
        self.assertEqual(result["score"], 5)

    def test_low_authorized_capital_has_soft_weight(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk([{"type": "low_authorized_capital_found", "source": "financials"}])

        self.assertEqual(result["score"], 8)
        self.assertEqual(result["level"], "low")
        self.assertFalse(result["hard_fact_present"])

    def test_financial_data_missing_has_soft_weight(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk([{"type": "financial_data_missing", "source": "financials"}])

        self.assertEqual(result["score"], 12)
        self.assertEqual(result["level"], "low")
        self.assertFalse(result["hard_fact_present"])

    def test_loss_flags_have_expected_weights(self):
        from app.services.risk_scoring import calculate_final_risk

        expected = {
            "small_loss_found": (
                5,
                "Компанія має невеликий збиток, але сам по собі він не є критичним.",
            ),
            "medium_loss_found": (5, "Компанія має помірний збиток."),
            "large_loss_found": (
                10,
                "Компанія має збиток; його масштаб потрібно оцінювати відносно активів і доходу.",
            ),
            "very_large_loss_found": (20, "Компанія має великий збиток, що потребує уваги."),
            "critical_loss_found": (
                35,
                "Компанія має критичний збиток відносно активів, доходу або на фоні проблемного балансу.",
            ),
        }

        for flag_type, (expected_score, expected_description) in expected.items():
            with self.subTest(flag_type=flag_type):
                result = calculate_final_risk([{"type": flag_type, "source": "financials"}])

                self.assertEqual(result["score"], expected_score)
                self.assertEqual(result["reasons"][0]["type"], flag_type)
                self.assertEqual(result["reasons"][0]["description"], expected_description)
                self.assertFalse(result["hard_fact_present"])

    def test_weak_public_financial_profile_combines_low_capital_and_missing_finance(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "low_authorized_capital_found", "source": "financials"},
                {"type": "financial_data_missing", "source": "financials"},
                {"type": "weak_public_financial_profile", "source": "financials"},
            ]
        )

        self.assertEqual(result["score"], 25)
        self.assertEqual(result["level"], "medium")
        self.assertFalse(result["hard_fact_present"])

    def test_prozorro_unconfirmed_search_noise_uses_minimum_score(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk([{"type": "prozorro_unconfirmed_search_noise", "source": "prozorro_search"}])

        self.assertEqual(result["score"], 5)
        self.assertEqual(result["level"], "low")
        self.assertFalse(result["hard_fact_present"])

    def test_low_capital_missing_finance_and_search_noise_stays_moderate(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "low_authorized_capital_found", "source": "financials"},
                {"type": "financial_data_missing", "source": "financials"},
                {"type": "weak_public_financial_profile", "source": "financials"},
                {"type": "prozorro_unconfirmed_search_noise", "source": "prozorro_search"},
            ]
        )

        self.assertEqual(result["score"], 27)
        self.assertEqual(result["level"], "medium")
        self.assertFalse(result["hard_fact_present"])

    def test_information_floor_uses_maximum_not_sum(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "court_cases_found", "source": "opendatabot"},
                {"type": "many_court_mentions_found", "source": "opendatabot"},
                {"type": "prozorro_sale_debtor_mention", "source": "prozorro_sale"},
                {"type": "prozorro_sale_informational_auction_mention", "source": "prozorro_sale"},
                {"type": "very_strong_financial_profile", "source": "financials"},
            ]
        )

        self.assertEqual(result["information_floor"], 5)
        self.assertEqual(result["score"], 5)

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

    def test_source_unavailable_has_minimum_score(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk([{"type": "source_unavailable", "source": "youcontrol"}])

        self.assertEqual(result["score"], 5)
        self.assertEqual(result["level"], "low")

    def test_tax_source_unavailable_has_minimum_score_without_reasons(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk([{"type": "tax_source_unavailable", "source": "tax"}])

        self.assertEqual(result["score"], 5)
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
        self.assertEqual(result["score"], 5)
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

    def test_debt_tax_and_court_cluster_without_terminal_critical_fact_is_not_100(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "large_tax_debt_found", "source": "clarity_project"},
                {"type": "tax_debt_found", "source": "opendatabot"},
                {"type": "enforcement_found", "source": "clarity_project"},
                {"type": "many_enforcement_proceedings_found", "source": "clarity_project"},
                {"type": "many_court_mentions_found", "source": "opendatabot"},
                {"type": "court_cases_found", "source": "opendatabot"},
                {"type": "low_statutory_capital_with_debt", "source": "opendatabot"},
            ]
        )

        self.assertEqual(result["score"], 80)
        self.assertEqual(result["level"], "high")
        self.assertTrue(result["hard_fact_present"])
        self.assertFalse(result["maximum_risk_confirmed"])

    def test_bankruptcy_plus_enforcement_is_confirmed_critical_cluster(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "bankruptcy_found", "source": "clarity_project"},
                {"type": "enforcement_found", "source": "clarity_project"},
            ]
        )

        self.assertEqual(result["score"], 100)
        self.assertEqual(result["level"], "critical")
        self.assertTrue(result["maximum_risk_confirmed"])

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
                {"type": "supplier_disqualified", "source": "prozorro_analysis"},
                {"type": "single_buyer_concentration", "source": "prozorro_analysis"},
            ]
        )

        self.assertEqual(
            [reason["type"] for reason in result["reasons"]],
            [
                "multiple_prozorro_terminations_found",
                "frequent_prozorro_disqualifications",
                "supplier_disqualified",
                "single_buyer_concentration",
            ],
        )
        self.assertEqual([reason["weight"] for reason in result["reasons"]], [35, 20, 10, 15])
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

    def test_prozorro_sale_confirmed_risk_has_significant_weight(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk([{"type": "prozorro_sale_risky_auction", "source": "prozorro_sale"}])

        self.assertEqual(result["score"], 35)
        self.assertEqual(result["reasons"][0]["type"], "prozorro_sale_risky_auction")
        self.assertEqual(result["reasons"][0]["sources"], ["prozorro_sale"])

    def test_prozorro_sale_specific_risk_markers_have_stronger_weights(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {
                    "type": "prozorro_sale_risky_auction",
                    "source": "prozorro_sale",
                    "raw_text": "BSE001-UA-20260601-12345 — переможець не виконав умови",
                },
                {
                    "type": "prozorro_sale_risky_auction",
                    "source": "prozorro_sale",
                    "raw_text": "SPE001-UA-20260602-12345 — відмова від підписання",
                },
            ]
        )

        self.assertEqual(
            [reason["type"] for reason in result["reasons"]],
            ["prozorro_sale_failed_obligations", "prozorro_sale_refusal_to_sign"],
        )
        self.assertEqual([reason["weight"] for reason in result["reasons"]], [45, 45])

    def test_prozorro_sale_bankruptcy_asset_sale_is_strong_bankruptcy_related_flag(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {
                    "type": "prozorro_sale_bankruptcy_asset_sale",
                    "source": "prozorro_sale",
                    "raw_text": "Продаж майна, яке увійшло до ліквідаційної маси банкрута.",
                }
            ]
        )

        self.assertGreaterEqual(result["score"], 70)
        self.assertIn(result["level"], {"high", "critical"})

    def test_prozorro_sale_debtor_mention_is_informational(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {
                    "type": "prozorro_sale_debtor_mention",
                    "source": "prozorro_sale",
                    "raw_text": "UA-PS-2021-08-20-000052-3 — компанія згадується як дебіторська заборгованість банкрута.",
                }
            ]
        )

        self.assertEqual(result["score"], 5)
        self.assertEqual(result["information_floor"], 3)
        self.assertEqual(result["level"], "low")
        self.assertEqual(result["reasons"][0]["type"], "prozorro_sale_debtor_mention")
        self.assertEqual(result["reasons"][0]["weight"], 0)

    def test_prozorro_sale_unsuccessful_auction_without_company_fault_is_informational(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {
                    "type": "prozorro_sale_risky_auction",
                    "source": "prozorro_sale",
                    "raw_text": "SPE001-UA-20260401-11111 — аукціон не відбувся",
                }
            ]
        )

        self.assertEqual(result["score"], 5)
        self.assertEqual(result["information_floor"], 3)
        self.assertEqual(result["level"], "low")
        self.assertEqual(result["reasons"][0]["type"], "prozorro_sale_informational_auction_mention")
        self.assertEqual(result["reasons"][0]["weight"], 0)

    def test_score_breakdown_is_logged(self):
        from app.services.risk_scoring import calculate_final_risk

        with self.assertLogs("app.services.risk_scoring", level="INFO") as logs:
            result = calculate_final_risk(
                [
                    {"type": "bankruptcy_found", "source": "opendatabot"},
                    {"type": "company_in_termination", "source": "opendatabot"},
                ]
            )

        output = "\n".join(logs.output)
        self.assertIn("raw_score=", output)
        self.assertIn("final_score=", output)
        self.assertIn("score_after_reducer=", output)
        self.assertIn("information_floor=", output)
        self.assertIn("applied_flags=", output)
        self.assertIn("hard_flags=", output)
        self.assertIn("max_hard_flag_weight=", output)
        self.assertEqual(result["score"], result["final_score"])


if __name__ == "__main__":
    unittest.main()
