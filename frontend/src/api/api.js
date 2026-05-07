const API_BASE_URL = process.env.REACT_APP_API_URL || "http://localhost:8000";

export const getAIMessage = async (userQuery, sessionId = "frontend-session") => {
  try {
    const response = await fetch(`${API_BASE_URL}/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message: userQuery,
        session_id: sessionId,
      }),
    });

    if (!response.ok) {
      throw new Error(`Backend error: ${response.status}`);
    }

    const data = await response.json();

    return {
      role: "assistant",
      content: data.answer || "Sorry, I could not generate an answer.",
      intent: data.intent || "",
      products: data.products || [],
      sources: data.sources || [],
      suggested_actions: data.suggested_actions || [],
      needs_model_number: data.needs_model_number || false,
    };
  } catch (error) {
    console.error("API error:", error);

    return {
      role: "assistant",
      content:
        "I could not connect to the backend. Please make sure FastAPI is running on http://localhost:8000.",
      intent: "error",
      products: [],
      sources: [],
      suggested_actions: [],
      needs_model_number: false,
    };
  }
};