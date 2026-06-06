import unittest


class CourtAnalyzerTests(unittest.TestCase):
    def test_claim_request_before_operative_part_does_not_create_liability(self):
        from app.services.court_analyzer import analyze_court_decision

        text = (
            "Позивач просить суд стягнути з відповідача 12 500 грн пені. "
            "Суд дослідив матеріали справи. "
            "УХВАЛИВ: Відкрити провадження у справі. "
            "Запропонувати відповідачу подати відзив протягом встановленого строку."
        )

        result = analyze_court_decision(text)

        self.assertTrue(result.procedural_decision_detected)
        self.assertFalse(result.liability_detected)
        self.assertFalse(result.negative_outcome_detected)
        self.assertIn("Відкрити провадження", result.operative_part_excerpt)
        self.assertEqual(result.risk_level, "medium")
        self.assertEqual(
            result.risk_summary,
            "Компанія є відповідачем у справі про стягнення санкцій/пені, але документ є процесуальною ухвалою і не підтверджує фактичне стягнення.",
        )

    def test_opening_proceedings_is_procedural_decision(self):
        from app.services.court_analyzer import analyze_court_decision

        text = (
            "У Х В А Л И В: Відкрити провадження у справі. "
            "Витребувати докази. "
            "Запропонувати відповідачу подати відзив."
        )

        result = analyze_court_decision(text)

        self.assertTrue(result.procedural_decision_detected)
        self.assertFalse(result.liability_detected)
        self.assertFalse(result.negative_outcome_detected)

    def test_motion_about_suspending_proceedings_is_procedural_decision(self):
        from app.services.court_analyzer import analyze_court_decision

        text = (
            "Суд розглянув клопотання сторони. "
            "УХВАЛИВ: В задоволенні клопотання про зупинення провадження у справі - відмовити. "
            "Ухвала може бути оскаржена."
        )

        result = analyze_court_decision(text)

        self.assertTrue(result.procedural_decision_detected)
        self.assertFalse(result.liability_detected)
        self.assertFalse(result.negative_outcome_detected)

    def test_negative_outcome_in_operative_part_detects_liability(self):
        from app.services.court_analyzer import analyze_court_decision

        text = (
            "Суд розглянув справу. "
            "ВИРІШИВ: Стягнути з відповідача 42 000 грн заборгованості. "
            "Рішення може бути оскаржене."
        )

        result = analyze_court_decision(text)

        self.assertFalse(result.procedural_decision_detected)
        self.assertTrue(result.liability_detected)
        self.assertTrue(result.negative_outcome_detected)
        self.assertEqual(result.claimed_amount_uah, 42000)
        self.assertIn("Стягнути з відповідача", result.operative_part_excerpt)

    def test_postanovyv_marker_is_used_for_operative_part_excerpt(self):
        from app.services.court_analyzer import analyze_court_decision

        text = "Вступна частина. ПОСТАНОВИВ: Накласти штраф у розмірі 3 000 грн."

        result = analyze_court_decision(text)

        self.assertTrue(result.liability_detected)
        self.assertTrue(result.negative_outcome_detected)
        self.assertEqual(result.claimed_amount_uah, 3000)
        self.assertEqual(result.operative_part_excerpt, "Накласти штраф у розмірі 3 000 грн.")

    def test_operative_part_excerpt_is_capped_at_700_characters(self):
        from app.services.court_analyzer import analyze_court_decision

        long_operative_part = "Відкрити провадження. " + ("Додатковий текст. " * 80)
        text = f"Суд встановив обставини. УХВАЛИВ: {long_operative_part}"

        result = analyze_court_decision(text)

        self.assertEqual(len(result.operative_part_excerpt), 700)
        self.assertTrue(result.operative_part_excerpt.startswith("Відкрити провадження."))


if __name__ == "__main__":
    unittest.main()
