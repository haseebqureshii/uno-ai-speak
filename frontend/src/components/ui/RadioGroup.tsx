"use client";

interface RadioOption {
  value: string;
  label: string;
  description?: string;
  disabled?: boolean;
}

interface RadioGroupProps {
  name: string;
  value: string;
  options: RadioOption[];
  onChange: (value: string) => void;
  label?: string;
}

export function RadioGroup({ name, value, options, onChange, label }: RadioGroupProps) {
  return (
    <fieldset className="space-y-3">
      {label && (
        <legend className="mb-2 text-sm font-semibold text-slate-700">{label}</legend>
      )}
      {options.map((option) => (
        <label
          key={option.value}
          className={`flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition ${
            value === option.value
              ? "border-tutor-500 bg-tutor-50"
              : "border-slate-200 bg-white hover:border-slate-300"
          } ${option.disabled ? "opacity-50 cursor-not-allowed" : ""}`}
        >
          <input
            type="radio"
            name={name}
            value={option.value}
            checked={value === option.value}
            disabled={option.disabled}
            onChange={() => onChange(option.value)}
            className="mt-1 h-4 w-4 text-tutor-700 focus:ring-tutor-500"
          />
          <div>
            <span className="block font-medium text-slate-900">{option.label}</span>
            {option.description && (
              <span className="block text-sm text-slate-500">{option.description}</span>
            )}
          </div>
        </label>
      ))}
    </fieldset>
  );
}
