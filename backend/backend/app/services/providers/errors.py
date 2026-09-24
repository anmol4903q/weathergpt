class WeatherAuthError(Exception):
    """API key rejected — likely not activated yet or genuinely invalid."""


class WeatherServiceError(Exception):
    """Any other non-2xx response from the weather provider."""
