from flask import Flask, render_template, request, redirect, url_for  # pyright: ignore[reportMissingImports]
from azure.data.tables import TableServiceClient   # pyright: ignore[reportMissingImports]

app = Flask(__name__)

if __name__ == "__main__":
    app.run(debug=True)

