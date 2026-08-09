from .config import Config, load_config
from .browser.context import BrowserContext
from .llm.base import BaseLLM
from .llm.groq import OpenAICompatLLM
from .llm.ollama import OllamaLLM
from .logging_setup import setup_logging
from .server.provider_utils import (
    coerce_provider_model,
    coerce_ui_provider,
    default_base_url,
    runtime_provider,
)
from .storage.llm_settings import LlmSettingsStore
from .agent.executor import Executor
from rich.console import Console
from rich.panel import Panel


console = Console()


def _config_for_provider_model(
    config: Config,
    ui_provider: str,
    model: str | None = None,
    *,
    openrouter_provider: str | None = None,
) -> Config:
    """Return a Config copy wired for a specific UI provider and model."""
    canonical = coerce_ui_provider(ui_provider)
    runtime = runtime_provider(canonical)
    settings = LlmSettingsStore().ensure_loaded()
    catalog = settings.get_provider(canonical)
    base_url = catalog.base_url or default_base_url(canonical)
    resolved_model = coerce_provider_model(
        canonical,
        model or config.active_model,
        base_url=base_url,
    )
    llm_config = config.model_copy(deep=True)
    llm_config.llm_provider = runtime
    llm_config.active_provider = canonical
    llm_config.active_model = resolved_model
    if openrouter_provider is not None and canonical == "openrouter":
        llm_config.openrouter_provider = openrouter_provider.strip()
    if runtime == "groq":
        llm_config.groq_model = resolved_model
        llm_config.openai_base_url = base_url
    elif runtime == "google":
        llm_config.google_model = resolved_model
        llm_config.openai_base_url = base_url
    elif runtime == "openrouter":
        llm_config.openrouter_model = resolved_model
        llm_config.openai_base_url = base_url
    else:
        llm_config.ollama_model = resolved_model
        llm_config.ollama_base_url = base_url
        if canonical == "ollama-cloud":
            llm_config.ollama_cloud_base_url = base_url
    return llm_config


def create_llm(
    config: Config,
    provider: str | None = None,
    model: str | None = None,
    *,
    openrouter_provider: str | None = None,
) -> BaseLLM:
    ui_provider = coerce_ui_provider(provider or config.active_provider or config.llm_provider or "groq")
    runtime = runtime_provider(ui_provider)
    llm_config = _config_for_provider_model(
        config,
        ui_provider,
        model,
        openrouter_provider=openrouter_provider,
    )
    if runtime == "ollama":
        llm = OllamaLLM(llm_config)
    else:
        llm = OpenAICompatLLM(llm_config, provider=runtime)
    llm.set_billing_provider(ui_provider)
    return llm


def create_role_llms(config: Config) -> tuple[BaseLLM, BaseLLM]:
    """Build navigation and planning LLM clients from a run config."""
    nav_provider = coerce_ui_provider(config.active_provider or config.llm_provider)
    nav_model = config.active_model
    plan_provider = coerce_ui_provider(
        config.active_planning_provider or config.planner_llm_provider or nav_provider
    )
    plan_model = config.planner_model or nav_model
    plan_openrouter = ""
    if plan_provider == "openrouter":
        plan_openrouter = config.planning_openrouter_provider or ""
    nav_llm = create_llm(config, nav_provider, nav_model)
    if plan_provider == nav_provider and plan_model == nav_model:
        if plan_provider != "openrouter" or not plan_openrouter or plan_openrouter == config.openrouter_provider:
            return nav_llm, nav_llm
    planner_llm = create_llm(
        config,
        plan_provider,
        plan_model,
        openrouter_provider=plan_openrouter or None,
    )
    return nav_llm, planner_llm


def run_task(task: str, config: Config) -> str | None:
    llm, planner_llm = create_role_llms(config)
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
    setup_logging()
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
