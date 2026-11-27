<?php

declare(strict_types=1);

namespace App\Http\Requests;

use App\Support\ApiResponse;
use Illuminate\Contracts\Validation\Validator as ValidatorContract;
use Illuminate\Foundation\Http\FormRequest;
use Illuminate\Http\Exceptions\HttpResponseException;
use Illuminate\Support\Str;
use Illuminate\Validation\Validator;

class RegistroRequest extends FormRequest
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

        if (isset($data['nombre']) && is_string($data['nombre'])) {
            $this->merge([
                'nombre' => trim($data['nombre']),
            ]);
        }

        if (isset($data['correo']) && is_string($data['correo'])) {
            $this->merge([
                'correo' => Str::lower(trim($data['correo'])),
            ]);
        }
    }

    public function rules(): array
    {
        return [
            'nombre' => [
                'bail',
                'required',
                'string',
                'min:1',
                'max:120',
                'not_regex:/\x00/',
            ],

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
                'min:8',
                'max:128',
            ],
        ];
    }

    public function after(): array
    {
        return [
            function (Validator $validator): void {
                $allowed = [
                    'nombre',
                    'correo',
                    'contrasena',
                ];

                $unexpected = array_diff(
                    array_keys($this->validationData()),
                    $allowed
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
            'nombre.required' => 'El nombre es obligatorio.',
            'nombre.string' => 'El nombre debe ser texto.',
            'nombre.min' => 'El nombre no puede estar vacío.',
            'nombre.max' => 'El nombre no puede superar 120 caracteres.',
            'nombre.not_regex' => 'El nombre contiene caracteres no permitidos.',

            'correo.required' => 'El correo es obligatorio.',
            'correo.string' => 'El correo debe ser texto.',
            'correo.email' => 'El correo no tiene un formato válido.',
            'correo.max' => 'El correo no puede superar 254 caracteres.',
            'correo.not_regex' => 'El correo contiene caracteres no permitidos.',

            'contrasena.required' => 'La contraseña es obligatoria.',
            'contrasena.string' => 'La contraseña debe ser texto.',
            'contrasena.min' => 'La contraseña debe tener al menos 8 caracteres.',
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
