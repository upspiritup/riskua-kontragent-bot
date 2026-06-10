import unittest
import urllib.error
import urllib.request


class CloudRunHealthServerTests(unittest.TestCase):
    def test_health_server_returns_ok_for_cloud_run_paths(self):
        from app.health import start_health_server

        health_server = start_health_server(port=0, host="127.0.0.1")
        try:
            for path in ("/", "/healthz"):
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{health_server.port}{path}",
                    timeout=2,
                ) as response:
                    body = response.read().decode("utf-8")

                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), "text/plain")
                self.assertEqual(body, "ok\n")
        finally:
            health_server.shutdown()

    def test_health_server_returns_not_found_for_unknown_paths(self):
        from app.health import start_health_server

        health_server = start_health_server(port=0, host="127.0.0.1")
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{health_server.port}/missing",
                    timeout=2,
                )

            self.assertEqual(error.exception.code, 404)
        finally:
            health_server.shutdown()


if __name__ == "__main__":
    unittest.main()
