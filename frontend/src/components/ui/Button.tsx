import { AnchorHTMLAttributes, ButtonHTMLAttributes, forwardRef } from "react";

type NativeButtonProps = ButtonHTMLAttributes<HTMLButtonElement>;
type NativeAnchorProps = AnchorHTMLAttributes<HTMLAnchorElement>;

interface SharedButtonProps {
  variant?: "primary" | "secondary" | "danger" | "ghost" | "outline";
  size?: "sm" | "md" | "lg";
}

interface ButtonAsButtonProps extends NativeButtonProps, SharedButtonProps {
  asLink?: false;
  href?: never;
}

interface ButtonAsLinkProps extends NativeAnchorProps, SharedButtonProps {
  asLink: true;
  href: string;
}

type ButtonProps = ButtonAsButtonProps | ButtonAsLinkProps;

export const Button = forwardRef<HTMLButtonElement | HTMLAnchorElement, ButtonProps>(
  ({ variant = "primary", size = "md", className = "", children, ...props }, ref) => {
    const base =
      "inline-flex items-center justify-center rounded-lg font-medium transition focus:outline-none focus:ring-2 focus:ring-offset-2 disabled:opacity-50 disabled:pointer-events-none";

    const variants = {
      primary: "bg-tutor-700 text-white hover:bg-tutor-500 focus:ring-tutor-500 shadow",
      secondary:
        "bg-white text-slate-700 border border-slate-300 hover:bg-slate-50 focus:ring-slate-400",
      danger: "bg-red-600 text-white hover:bg-red-500 focus:ring-red-500 shadow",
      ghost: "bg-transparent text-slate-600 hover:bg-slate-100 focus:ring-slate-400",
      outline:
        "bg-transparent text-slate-700 border border-slate-300 hover:bg-slate-50 focus:ring-slate-400",
    };

    const sizes = {
      sm: "px-3 py-1.5 text-sm",
      md: "px-5 py-2.5 text-base",
      lg: "px-8 py-4 text-lg",
    };

    const classes = `${base} ${variants[variant]} ${sizes[size]} ${className}`;

    if ("asLink" in props && props.asLink) {
      const { asLink: _, ...anchorProps } = props as ButtonAsLinkProps;
      return (
        <a
          ref={ref as React.Ref<HTMLAnchorElement>}
          className={classes}
          {...anchorProps}
        >
          {children}
        </a>
      );
    }

    return (
      <button
        ref={ref as React.Ref<HTMLButtonElement>}
        className={classes}
        {...(props as NativeButtonProps)}
      >
        {children}
      </button>
    );
  }
);

Button.displayName = "Button";
