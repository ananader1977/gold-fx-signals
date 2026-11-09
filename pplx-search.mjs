import Perplexity from "@perplexity-ai/perplexity_ai";

const client = new Perplexity();

const response = await client.responses.create({
  model: "openai/gpt-5.6-terra",
  input: "What are the latest developments in AI inference hardware?",
  tools: [{ type: "web_search" }],
  instructions:
    "You have access to a web_search tool. Use it for questions about current events, news, or recent developments.",
});

if (response.status === "completed") {
  console.log(response.output_text);
}
