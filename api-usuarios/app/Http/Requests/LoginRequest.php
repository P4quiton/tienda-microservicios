<?php

declare(strict_types=1);

namespace App\Http\Requests;

use App\Support\ApiResponse;
use Illuminate\Contracts\Validation\Validator as ValidatorContract;
use Illuminate\Foundation\Http\FormRequest;
use Illuminate\Http\Exceptions\HttpResponseException;
use Illuminate\Support\Str;
use Illuminate\Validation\Validator;

class LoginRequest extends FormRequest
{
    public function authorize(): bool
    {
        return true;
    }

    public function validationData(): array
    {
        return $this->json()->all();
    }

    protected function prepareForValidation(): void
    {
        $data = $this->json()->all();

        if (isset($data['correo']) && is_string($data['correo'])) {
            $this->merge([
                'correo' => Str::lower(trim($data['correo'])),
            ]);
        }
    }

    public function rules(): array
    {
        return [
            'correo' => [
                'bail',
                'required',
                'string',
                'max:254',
                'email:rfc',
                'not_regex:/\x00/',
            ],

            'contrasena' => [
                'bail',
                'required',
                'string',
                'max:128',
            ],
        ];
    }

    public function after(): array
    {
        return [
            function (Validator $validator): void {
                $unexpected = array_diff(
                    array_keys($this->validationData()),
                    ['correo', 'contrasena']
                );

                if ($unexpected !== []) {
                    $validator->errors()->add(
                        'body',
                        'La petición contiene campos no permitidos.'
                    );
                }
            },
        ];
    }

    public function messages(): array
    {
        return [
            'correo.required' => 'El correo es obligatorio.',
            'correo.string' => 'El correo debe ser texto.',
            'correo.email' => 'El correo no tiene un formato válido.',
            'correo.max' => 'El correo no puede superar 254 caracteres.',
            'correo.not_regex' => 'El correo contiene caracteres no permitidos.',

            'contrasena.required' => 'La contraseña es obligatoria.',
            'contrasena.string' => 'La contraseña debe ser texto.',
            'contrasena.max' => 'La contraseña no puede superar 128 caracteres.',
        ];
    }

    protected function failedValidation(
        ValidatorContract $validator
    ): void {
        throw new HttpResponseException(
            ApiResponse::error(
                'Error de validación.',
                422,
                $validator->errors()->toArray()
            )
        );
    }
}
