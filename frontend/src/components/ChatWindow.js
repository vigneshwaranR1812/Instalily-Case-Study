import React, { useState, useEffect, useRef } from "react";
import "./ChatWindow.css";
import { getAIMessage } from "../api/api";
import { marked } from "marked";

function ChatWindow() {
  const defaultMessage = [
    {
      role: "assistant",
      content:
        "Hi, I’m your PartSelect assistant. I can help with refrigerator and dishwasher parts, compatibility, installation, and troubleshooting.",
      intent: "welcome",
      products: [],
      sources: [],
      suggested_actions: [],
    },
  ];

  const [messages, setMessages] = useState(defaultMessage);
  const [input, setInput] = useState("");
  const [modelNumber, setModelNumber] = useState("");
  const [loading, setLoading] = useState(false);

  const messagesEndRef = useRef(null);

  if (!localStorage.getItem("session_id")) {
    localStorage.setItem("session_id", crypto.randomUUID());
  }

  const sessionId = useRef(localStorage.getItem("session_id"));

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading]);

  const sendMessage = async (text) => {
    const userText = text.trim();
    if (!userText || loading) return;

    setMessages((prev) => [
      ...prev,
      { role: "user", content: userText, products: [], sources: [], suggested_actions: [] },
    ]);

    setInput("");
    setLoading(true);

    const newMessage = await getAIMessage(userText, sessionId.current);

    setMessages((prev) => [...prev, newMessage]);
    setLoading(false);
  };

  const handleSend = async () => {
    await sendMessage(input);
  };

  const handleCompatibilityClick = async (partNumber) => {
    const cleanModel = modelNumber.trim();

    if (!cleanModel) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Please enter your appliance model number first, then click Check compatibility.",
          products: [],
          sources: [],
          suggested_actions: [],
        },
      ]);
      return;
    }

    await sendMessage(`Is ${partNumber} compatible with my model ${cleanModel}?`);
  };

  const renderRating = (ratingValue, ratingCount) => {
    if (!ratingValue && !ratingCount) return null;

    const rating = Number(ratingValue || 0);
    const stars = "★★★★★";

    return (
      <div className="rating-row">
        <span className="stars">{stars}</span>
        {ratingValue && <strong>{rating.toFixed(1)}</strong>}
        {ratingCount && <span>({ratingCount} reviews)</span>}
      </div>
    );
  };

  
  const renderProducts = (products = [], suggestedActions = []) => {
    if (!products.length) return null;

    return (
      <div className="product-showcase">
        <div className="section-label">Matched product</div>

        <div className="model-check-panel">
          <span>Have a model number?</span>
          <input
            value={modelNumber}
            onChange={(e) => setModelNumber(e.target.value.toUpperCase())}
            placeholder="e.g. WDT780SAEM1"
          />
        </div>

        {products.map((product, index) => {
          const partNumber = product.partselect_number;
          const hasCompatibilityAction =
            suggestedActions.some(
              (a) =>
                a.type === "check_compatibility" &&
                a.part_number === partNumber
            ) || Boolean(partNumber);

          return (
            <div className="premium-product-card" key={index}>
              <div className="product-visual">
                {product.main_image ? (
                  <img
                    src={product.main_image}
                    alt={product.name || "Part image"}
                    className="premium-product-image"
                  />
                ) : (
                  <div className="image-placeholder">Part</div>
                )}
              </div>

              <div className="premium-product-info">
                <div className="product-topline">
                  {partNumber && <span className="part-badge">{partNumber}</span>}
                  {product.availability && (
                    <span className="stock-badge">{product.availability}</span>
                  )}
                </div>

                <h3>{product.name || "PartSelect Product"}</h3>
                {product.symptoms?.length > 0 && (
                  <div className="symptoms-container">
                    <div className="symptoms-label">
                      {product.symptoms.length > 1 ? "Fixes issues:" : "Fixes issue:"}
                    </div>

                    <div className="symptoms-tags">
                      {product.symptoms.map((s, i) => (
                        <span key={i} className="symptom-pill">
                          {s}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {renderRating(product.rating_value, product.rating_count)}

                <div className="product-detail-grid">
                  {product.price && (
                    <div>
                      <span>Price</span>
                      <strong>{product.price}</strong>
                    </div>
                  )}

                  {product.installation_complexity && (
                    <div>
                      <span>Install difficulty</span>
                      <strong>{product.installation_complexity}</strong>
                    </div>
                  )}

                  {product.installation_time && (
                    <div>
                      <span>Install time</span>
                      <strong>{product.installation_time}</strong>
                    </div>
                  )}

                  {product.rating_count && (
                    <div>
                      <span>Customer reviews</span>
                      <strong>{product.rating_count}</strong>
                    </div>
                  )}
                </div>

                <div className="product-actions">
                  {hasCompatibilityAction && (
                    <button
                      className="compatibility-button"
                      onClick={() => handleCompatibilityClick(partNumber)}
                    >
                      Check compatibility
                    </button>
                  )}

                  {product.video_url && (
                    <a
                      href={product.video_url}
                      target="_blank"
                      rel="noreferrer"
                      className="secondary-product-link"
                    >
                      Watch video
                    </a>
                  )}

                  {product.product_url && (
                    <a
                      href={product.product_url}
                      target="_blank"
                      rel="noreferrer"
                      className="primary-product-link"
                    >
                      View product
                    </a>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    );
  };
  const renderCompatibleModels = (message) => {
  if (message.intent !== "compatible_models_lookup") return null;

  const models = message.sources || [];

  if (!models.length) return null;

  const partNumber =
    models[0]?.partselect_number ||
    models[0]?.part_number ||
    "this part";

  return (
    <div className="compatible-models-card">
      <div className="section-label">Compatibility list</div>

      <h3>Compatible models for {partNumber}</h3>

      <div className="compatible-table-wrap">
        <table className="compatible-table">
          <thead>
            <tr>
              <th>Brand</th>
              <th>Model Number</th>
            </tr>
          </thead>

          <tbody>
            {models.map((model, index) => (
              <tr key={index}>
                <td>
                  <span className="brand-badge">
                    {model.brand || "Unknown"}
                  </span>
                </td>
                <td>
                  {model.model_url ? (
                    <a
                      href={model.model_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {model.model_number}
                    </a>
                  ) : (
                    model.model_number || "-"
                  )}
                </td>
                
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
  const renderSources = (sources = []) => {
    if (!sources.length) return null;

    return (
      <details className="premium-sources-box">
        <summary>Evidence used by the assistant</summary>

        <div className="source-grid">
          {sources.slice(0, 5).map((source, index) => (
            <div className="premium-source-card" key={index}>
              <div className="source-pill">{source.source || "source"}</div>
              {source.title && <strong>{source.title}</strong>}
              {source.symptom && <span>Symptom: {source.symptom}</span>}
              {source.part && <span>Part: {source.part}</span>}
              {source.model_number && <span>Model: {source.model_number}</span>}
              {source.appliance && <span>Appliance: {source.appliance}</span>}
            </div>
          ))}
        </div>
      </details>
    );
  };

  return (
    <main className="chat-page">
      <section className="hero-panel">
        <div>
          <p className="eyebrow">PartSelect Assistant</p>
          <h1>Find the right part. Fix it with confidence.</h1>
          <p className="hero-subtitle">
            Ask about refrigerator and dishwasher parts, model compatibility,
            installation steps, and troubleshooting.
          </p>
        </div>

        <div className="suggestion-row">
          <button onClick={() => setInput("Show me part PS11752778")}>
            Product lookup
          </button>
          <button
            onClick={() =>
              setInput("Is part PS11752778 compatible with 10640262010?")
            }
          >
            Compatibility
          </button>
          <button
            onClick={() =>
              setInput("Dishwasher rack not sliding properly")
            }
          >
            Troubleshooting
          </button>
        </div>
      </section>

      <section className="chat-shell">
        <div className="messages-container">
          {messages.map((message, index) => (
            <div key={index} className={`${message.role}-message-container`}>
              <div className={`message ${message.role}-message`}>
                <div
                  dangerouslySetInnerHTML={{
                    __html: marked(message.content || "").replace(/<p>|<\/p>/g, ""),
                  }}
                />

                {renderProducts(message.products, message.suggested_actions)}
                {renderCompatibleModels(message)}
                {message.intent !== "compatible_models_lookup" && renderSources(message.sources)}
              </div>
            </div>
          ))}

          {loading && (
            <div className="assistant-message-container">
              <div className="message assistant-message typing">
                <span></span>
                <span></span>
                <span></span>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        <div className="input-area">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about a part, model compatibility, or repair issue..."
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                handleSend();
              }
            }}
          />
          <button className="send-button" onClick={handleSend} disabled={loading}>
            {loading ? "Thinking..." : "Send"}
          </button>
        </div>
      </section>
    </main>
  );
}

export default ChatWindow;