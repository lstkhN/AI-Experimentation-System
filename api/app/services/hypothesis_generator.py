"""Transparent starter hypothesis generation used before the LLM orchestrator exists."""
from app.db.models import Project


def starter_hypotheses(project: Project) -> list[dict[str, str | float]]:
    subject = project.description or project.name
    if project.language == "ru":
        statements = [
            ("problem", 0.9, f"Достижимый сегмент клиентов регулярно сталкивается с дорогостоящей проблемой, связанной с: {subject}."),
            ("customer", 0.8, f"Для решения, описанного как: {subject}, существует чётко определяемый покупатель."),
            ("solution", 0.7, f"Простое решение для {subject} может дать измеримое улучшение по сравнению с текущими альтернативами."),
            ("willingness_to_pay", 0.9, f"Целевой покупатель готов заплатить за решение проблемы: {subject}."),
            ("channel", 0.6, f"Целевого покупателя для {subject} можно привлечь через повторяемый и экономичный канал."),
        ]
    else:
        statements = [
            ("problem", 0.9, f"A reachable customer segment experiences a frequent, costly problem related to: {subject}."),
            ("customer", 0.8, f"There is a clearly identifiable buyer for the solution described as: {subject}."),
            ("solution", 0.7, f"A sufficiently simple solution to {subject} can produce a measurable improvement over current alternatives."),
            ("willingness_to_pay", 0.9, f"The target buyer for {subject} will commit money to solve the problem."),
            ("channel", 0.6, f"The target buyer for {subject} can be reached through a repeatable, affordable channel."),
        ]
    return [{"category": category, "importance": importance, "statement": statement} for category, importance, statement in statements]
