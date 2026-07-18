from .config import load_config, Config
from .browser.context import BrowserContext
from .llm.base import BaseLLM
from .llm.groq import OpenAICompatLLM
from .llm.ollama import OllamaLLM
from .server.provider_utils import runtime_provider
from .agent.executor import Executor
from rich.console import Console
from rich.panel import Panel


console = Console()


def create_llm(config: Config, provider: str | None = None) -> BaseLLM:
    selected = runtime_provider(provider or config.llm_provider or "groq")
    if selected == "ollama":
        return OllamaLLM(config)
    return OpenAICompatLLM(config, provider=selected)


def run_task(task: str, config: Config) -> str | None:
    llm = create_llm(config)
    planner_provider = config.planner_llm_provider or config.llm_provider
    planner_llm = create_llm(config, planner_provider) if planner_provider != config.llm_provider else llm
    browser_ctx = BrowserContext(config)
    browser_ctx.launch()
    browser_ctx.new_page(config.home_page_url)

    executor = Executor(task, browser_ctx, llm, config, planner_llm=planner_llm)
    console.print(Panel(task, title="Task", border_style="blue"))

    try:
        result = executor.execute()
        if result:
            console.print(Panel(result, title="Final Answer", border_style="green"))
        return result
    finally:
        executor.cleanup()


def main():
    config = load_config()

    console.print(Panel(
        "[bold]Smart Automator[/bold]\nAI-powered browser automation",
        border_style="bright_blue",
    ))

    console.print(f"Provider: [cyan]{config.llm_provider}[/cyan]")
    if config.llm_provider == "groq":
        console.print(f"Model: [cyan]{config.groq_model}[/cyan]")
    else:
        console.print(f"Model: [cyan]{config.ollama_model}[/cyan]")
    console.print(f"Headless: [cyan]{config.headless}[/cyan]")
    console.print(f"Max actions/step: [cyan]{config.max_actions_per_step}[/cyan]")
    console.print()

    while True:
        try:
            task = console.input("[bold green]Enter task (or 'quit' to exit):[/bold green] ").strip()
            if not task:
                continue
            if task.lower() in ("quit", "exit", "q"):
                break
            run_task(task, config)
            console.print()
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted[/dim]")
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")

    console.print("[dim]Goodbye![/dim]")


if __name__ == "__main__":
    main()
