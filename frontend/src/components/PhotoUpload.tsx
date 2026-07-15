import { useEffect, useId, useRef, useState, type ChangeEvent, type DragEvent } from "react";

interface Props { value: File | null; onChange: (file: File | null) => void }

export default function PhotoUpload({ value, onChange }: Props) {
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
      setError("Choose a JPEG, PNG, or WebP image.");
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setError("Photo must be 5 MiB or smaller.");
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
      <strong>Add a clear photo <span lang="hi">/ फोटो जोड़ें</span></strong>
      <span id={`${inputId}-hint`} className="field__hint">Take a photo or choose JPEG, PNG, or WebP · maximum 5 MiB</span>
      <span className="photo-drop__action">Choose photo</span>
      <input id={inputId} className="visually-hidden" ref={inputRef} type="file" accept="image/jpeg,image/png,image/webp" aria-invalid={Boolean(error)} aria-describedby={descriptionIds} capture="environment" onChange={handleFile} />
    </label>}
    {previewUrl && <figure className="photo-upload__preview">
      <img src={previewUrl} alt="Selected photo evidence for this complaint" width="720" height="480" />
      <figcaption>{value?.name} · {value ? `${(value.size / 1024 / 1024).toFixed(1)} MB` : "Photo selected"}</figcaption>
      <div className="photo-preview-actions">
        <button type="button" className="btn btn--secondary btn-sm" onClick={() => inputRef.current?.click()}>Change</button>
        <button type="button" className="btn-link" onClick={remove}>Remove</button>
      </div>
      <input id={`${inputId}-replace`} className="visually-hidden" ref={inputRef} type="file" accept="image/jpeg,image/png,image/webp" aria-invalid={Boolean(error)} aria-describedby={descriptionIds} capture="environment" onChange={handleFile} />
    </figure>}
  </div>;
}
