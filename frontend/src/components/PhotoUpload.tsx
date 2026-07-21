import { useEffect, useId, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { useI18n } from "../i18n/I18nContext";

interface Props { value: File | null; onChange: (file: File | null) => void }

export default function PhotoUpload({ value, onChange }: Props) {
  const { t } = useI18n();
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const descriptionIds = `${inputId}-hint${error ? ` ${inputId}-error` : ""}`;
  useEffect(() => {
    if (!value) { setPreviewUrl(null); return; }
    const url = URL.createObjectURL(value);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [value]);
  const choose = (file?: File) => {
    if (!file) return;
    const allowed = ["image/jpeg", "image/png", "image/webp"];
    if (!allowed.includes(file.type)) {
      setError(t.photoTypeError);
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setError(t.photoSizeError);
      return;
    }
    setError(null);
    onChange(file);
  };
  const handleFile = (event: ChangeEvent<HTMLInputElement>) => choose(event.target.files?.[0]);
  const drop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    choose(event.dataTransfer.files?.[0]);
  };
  const remove = () => {
    onChange(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  return <div className="photo-upload">
    {error && <p id={`${inputId}-error`} className="field-error" role="alert" tabIndex={-1}>{error}</p>}
    {!previewUrl && <label className="photo-drop" data-dragging={dragging || undefined} htmlFor={inputId} onDragEnter={() => setDragging(true)} onDragLeave={() => setDragging(false)} onDragOver={(event) => event.preventDefault()} onDrop={drop}>
      <span className="photo-drop__artifact" aria-hidden="true"><i /><b>+</b></span>
      <strong>{t.photoDropTitle}</strong>
      <span id={`${inputId}-hint`} className="field__hint">{t.photoDropHint}</span>
      <span className="photo-drop__action">{t.choosePhoto}</span>
      <input id={inputId} className="visually-hidden" ref={inputRef} type="file" accept="image/jpeg,image/png,image/webp" aria-invalid={Boolean(error)} aria-describedby={descriptionIds} capture="environment" onChange={handleFile} />
    </label>}
    {previewUrl && <figure className="photo-upload__preview">
      <img src={previewUrl} alt={t.photoAlt} width="720" height="480" />
      <figcaption>{value?.name} · {value ? `${(value.size / 1024 / 1024).toFixed(1)} MB` : t.photoSelected}</figcaption>
      <div className="photo-preview-actions">
        <button type="button" className="btn btn--secondary btn-sm" onClick={() => inputRef.current?.click()}>{t.changePhoto}</button>
        <button type="button" className="btn-link" onClick={remove}>{t.removePhoto}</button>
      </div>
      <input id={`${inputId}-replace`} className="visually-hidden" ref={inputRef} type="file" accept="image/jpeg,image/png,image/webp" aria-invalid={Boolean(error)} aria-describedby={descriptionIds} capture="environment" onChange={handleFile} />
    </figure>}
  </div>;
}
