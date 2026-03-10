from pathlib import Path
import webbrowser

def display_response_html():
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="utf-8">
    <title>NASA Fact Check</title>
    </head>
    <body>
    <p>The request was to verify: Jupiter has one moon. The utterance is not factual (0 likelihood). Jupiter has 79 known moons: Ganymede, Io, Europa, Callisto...</p>
    </body>
    </html>
    """

    file_path = Path.cwd() / "cards.html"
    file_path.write_text(html_content, encoding="utf-8")

    webbrowser.open(file_path.as_uri())

display_response_html()
