import { useEffect, useMemo, useRef, type ChangeEvent } from "react";

interface PhotoUploadProps {
  value: File | null;
  onChange: (file: File | null) => void;
}

export default function PhotoUpload({ value, onChange }: PhotoUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const previewUrl = useMemo(() => (value ? URL.createObjectURL(value) : null), [value]);

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    onChange(event.target.files?.[0] ?? null);
  };

  const handleRemove = () => {
    onChange(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div className="photo-upload">
      <input ref={inputRef} type="file" accept="image/*" onChange={handleFileChange} />
      {previewUrl && (
        <div className="photo-upload__preview">
          <img src={previewUrl} alt="Selected photo preview" />
          <button type="button" className="btn-link" onClick={handleRemove}>
            Remove photo
          </button>
        </div>
      )}
    </div>
  );
}
