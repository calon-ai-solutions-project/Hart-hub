import Icon from "./Icon.jsx";

/** The opening message: the enquiry form. The fields and wording come from the server. */
export default function EnquiryForm({ message, onSubmit }) {
  function submit(event) {
    event.preventDefault();
    const answers = Object.fromEntries(new FormData(event.currentTarget));
    if (Object.values(answers).some((value) => value.trim())) onSubmit(answers);
  }

  return (
    <div className="bubble wide">
      <div className="lead">{message.body}</div>
      <form className="form" onSubmit={submit}>
        {message.payload.fields.map((field) => (
          <label key={field.name}>
            {field.label}
            {field.options ? (
              <select name={field.name} defaultValue="">
                <option value="" />
                {field.options.map((option) => (
                  <option key={option}>{option}</option>
                ))}
              </select>
            ) : (
              <input name={field.name} placeholder={field.placeholder || ""} autoComplete="off" />
            )}
          </label>
        ))}
        <div className="actions">
          <button className="btn primary find">Find cars</button>
          <span className="hint">or just type what they want below</span>
        </div>
      </form>
      <div className="bonus">
        <Icon name="gift" />
        <span>{message.payload.bonus}</span>
      </div>
    </div>
  );
}
