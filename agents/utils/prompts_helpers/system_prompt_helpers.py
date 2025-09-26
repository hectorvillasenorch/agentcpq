from agents.models import AgentPrompt


def make_system_prompt(agent_name, method, function_name, previous_summary):
    try:
        agent_prompt = AgentPrompt.objects.get(agent_name=agent_name, method=method, function=function_name)
        print(f"\n✅ Agent prompt extracted successfully for {agent_name} {method} ✅")

        system_instructions = agent_prompt.system_instructions
        system_rules = agent_prompt.system_rules
        agent_message = agent_prompt.agent_message
        agent_summary = agent_prompt.agent_summary
        temperature = agent_prompt.temperature

        previous_summary = "Previous Summary: " + (previous_summary or "")
        system_prompt = system_instructions + system_rules + agent_message + agent_summary + previous_summary

        return system_prompt, temperature
    except AgentPrompt.DoesNotExist:
        print(f"\n❌ No AgentPrompt found for {agent_name} {method} ❌")
        return None  # Retorna None si no se encuentra
    except Exception as e:
        print(f"\n⚠️ Unexpected error while fetching AgentPrompt: {e} ⚠️")
        return None
