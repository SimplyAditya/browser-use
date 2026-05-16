# Browser-Use GUI Reference

The `browser-use` repository provides friendly Web-based Graphical User Interfaces (GUIs) to interact with the AI browser agent. 

These interfaces are located in the `examples/ui` directory.

## Prerequisites
Before running the GUIs, ensure you are in the project root and have the necessary dependencies installed using `uv` or `pip`.

```bash
cd /home/ubuntu/browser-use
uv sync
```

## 1. Running the Gradio GUI
Gradio provides a simple web interactive UI to chat with the agent and provide URLs or tasks.

**Command:**
```bash
python examples/ui/gradio_demo.py
```
After running this command, a local server will start. Open your web browser and navigate to the URL provided in the terminal (typically `http://127.0.0.1:7860`).

## 2. Running the Streamlit GUI
Streamlit provides a clean, alternative web dashboard experience for interacting with the browser-use agent.

**Command:**
```bash
python -m streamlit run examples/ui/streamlit_demo.py
```
This will start the Streamlit server. Open your web browser and navigate to the assigned URL (typically `http://localhost:8501`).

## Additional Interfaces
If you prefer a structured, interactive prompt directly in your terminal rather than a web browser interface, you can also run:
```bash
python examples/ui/command_line.py
```
